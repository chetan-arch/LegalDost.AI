"""Search indexes that scale to large corpora (hundreds of thousands of passages).

* ``LexicalIndex`` — keyword search. SQLite: an FTS5 table with Porter stemming and BM25
  ranking (``passages_fts``). PostgreSQL: the generated ``tsvector`` column with ``ts_rank_cd``.
* ``VectorIndex`` — embedding search. SQLite: all current passage vectors held in one in-memory
  NumPy matrix (cached as ``.npy`` under ``DATA_DIR``, rebuilt when the corpus changes).
  PostgreSQL: pgvector's cosine distance operator.

Both return candidate passage ids with scores; eligibility filters (current version, status,
jurisdiction, domain) are applied afterwards by the retriever on that small candidate set.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from legaldost.db.models import DocumentVersion, Passage

log = logging.getLogger(__name__)
_FTS_READY: set[str] = set()
_LOCK = threading.Lock()


def _dialect(session: Session) -> str:
    return session.get_bind().dialect.name


def _key(session: Session) -> str:
    return str(session.get_bind().engine.url)


class LexicalIndex:
    @staticmethod
    def ensure(session: Session) -> None:
        """Create the SQLite FTS table if needed and fill it once if it is empty."""
        if _dialect(session) != "sqlite" or _key(session) in _FTS_READY:
            return
        with _LOCK:
            exists = session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'passages_fts'")
            ).first()
            if exists is None:  # creating is a write: only do it when needed, never on every start
                session.execute(
                    text(
                        "CREATE VIRTUAL TABLE passages_fts USING fts5("
                        "passage_id UNINDEXED, body, tokenize = 'porter unicode61 remove_diacritics 2')"
                    )
                )
            empty = session.execute(text("SELECT 1 FROM passages_fts LIMIT 1")).first() is None
            if empty and session.execute(select(Passage.id).limit(1)).first() is not None:
                LexicalIndex.rebuild(session)
            _FTS_READY.add(_key(session))

    @staticmethod
    def rebuild(session: Session) -> int:
        if _dialect(session) != "sqlite":
            return 0
        session.execute(text("DELETE FROM passages_fts"))
        session.execute(
            text(
                "INSERT INTO passages_fts (passage_id, body) "
                "SELECT id, coalesce(section_label, '') || ' ' || text FROM passages"
            )
        )
        return int(session.execute(text("SELECT count(*) FROM passages_fts")).scalar() or 0)

    @staticmethod
    def add(session: Session, passages: list[Passage]) -> None:
        if _dialect(session) != "sqlite" or not passages:
            return
        LexicalIndex.ensure(session)
        # ensure() may have just built the table from these same (already flushed) passages.
        LexicalIndex.remove(session, [p.id for p in passages])
        session.execute(
            text("INSERT INTO passages_fts (passage_id, body) VALUES (:pid, :body)"),
            [{"pid": p.id, "body": f"{p.section_label or ''} {p.text}"} for p in passages],
        )

    @staticmethod
    def remove(session: Session, passage_ids: list[str]) -> None:
        if _dialect(session) != "sqlite" or not passage_ids:
            return
        LexicalIndex.ensure(session)
        for i in range(0, len(passage_ids), 500):
            chunk = passage_ids[i : i + 500]
            marks = ",".join(f":p{j}" for j in range(len(chunk)))
            session.execute(
                text(f"DELETE FROM passages_fts WHERE passage_id IN ({marks})"),  # noqa: S608
                {f"p{j}": pid for j, pid in enumerate(chunk)},
            )

    @staticmethod
    def search(session: Session, terms: list[str], limit: int) -> dict[str, float]:
        """Return {passage_id: score} for passages matching ANY of the terms (higher = better)."""
        words = sorted({t for t in terms if re.fullmatch(r"[a-z0-9]+", t)})
        if not words:
            return {}
        if _dialect(session) == "postgresql":
            rows = session.execute(
                text(
                    "SELECT id, ts_rank_cd(tsv, to_tsquery('english', :q)) AS r FROM passages "
                    "WHERE tsv @@ to_tsquery('english', :q) ORDER BY r DESC LIMIT :n"
                ),
                {"q": " | ".join(words), "n": limit},
            )
            return {row.id: float(row.r) for row in rows}
        LexicalIndex.ensure(session)
        query = " OR ".join(f'"{w}"' for w in words)
        rows = session.execute(
            text(
                "SELECT passage_id, bm25(passages_fts) AS r FROM passages_fts "
                "WHERE passages_fts MATCH :q ORDER BY r LIMIT :n"
            ),
            {"q": query, "n": limit},
        )
        return {row.passage_id: -float(row.r) for row in rows}  # FTS5 bm25: lower is better


class _Matrix:
    def __init__(self, revision: tuple[int, str], ids: list[str], matrix: np.ndarray) -> None:
        self.revision = revision
        self.ids = ids
        self.matrix = matrix


_MATRICES: dict[str, _Matrix] = {}


class VectorIndex:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    @staticmethod
    def _revision(session: Session) -> tuple[int, str]:
        count = session.scalar(select(func.count()).select_from(Passage)) or 0
        latest = session.scalar(select(func.max(DocumentVersion.created_at)))
        return int(count), str(latest)

    def _load(self, session: Session) -> _Matrix:
        revision = self._revision(session)
        key = _key(session)
        cached = _MATRICES.get(key)
        if cached and cached.revision == revision:
            return cached
        with _LOCK:
            cached = _MATRICES.get(key)
            if cached and cached.revision == revision:
                return cached
            tag = f"{revision[0]}_{abs(hash(revision[1])) % 10**8}"
            npy, ids_file = self.cache_dir / f"vectors_{tag}.npy", self.cache_dir / f"vectors_{tag}.ids"
            if npy.exists() and ids_file.exists():
                matrix = np.load(npy)
                ids = ids_file.read_text(encoding="utf-8").split()
            else:
                ids, matrix = self._refresh(session, cached)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                for old in self.cache_dir.glob("vectors_*"):
                    old.unlink(missing_ok=True)
                np.save(npy, matrix)
                ids_file.write_text("\n".join(ids), encoding="utf-8")
                log.info("vector index rebuilt: %d passages", len(ids))
            _MATRICES[key] = _Matrix(revision, ids, matrix)
            return _MATRICES[key]

    @staticmethod
    def _refresh(session: Session, cached: _Matrix | None) -> tuple[list[str], np.ndarray]:
        """Reuse rows of the previous matrix and read only embeddings that are new since then."""
        # ids only: answered from the primary-key index without reading the large embedding column
        current = list(session.scalars(select(Passage.id)))
        known: dict[str, int] = {}
        if cached is not None and len(cached.matrix) and cached.matrix.shape[1] > 1:
            known = {pid: i for i, pid in enumerate(cached.ids)}
        missing = [pid for pid in current if pid not in known]
        fresh: dict[str, list[float]] = {}
        for i in range(0, len(missing), 500):
            chunk = missing[i : i + 500]
            for pid, emb in session.execute(
                select(Passage.id, Passage.embedding).where(Passage.id.in_(chunk))
            ):
                if emb:
                    fresh[pid] = emb
        ids = [pid for pid in current if pid in known or pid in fresh]
        if not ids:
            return [], np.zeros((0, 1), dtype=np.float32)
        new_rows = np.asarray([fresh[pid] for pid in ids if pid in fresh], dtype=np.float32)
        if len(new_rows):
            new_rows = (new_rows / np.maximum(np.linalg.norm(new_rows, axis=1, keepdims=True), 1e-9)).astype(
                np.float32
            )
            if known and new_rows.shape[1] != cached.matrix.shape[1]:  # type: ignore[union-attr]
                return VectorIndex._refresh(session, None)
        dim = new_rows.shape[1] if len(new_rows) else cached.matrix.shape[1]  # type: ignore[union-attr]
        matrix = np.empty((len(ids), dim), dtype=np.float32)
        j = 0
        for i, pid in enumerate(ids):
            if pid in known:
                matrix[i] = cached.matrix[known[pid]]  # type: ignore[union-attr]
            else:
                matrix[i] = new_rows[j]
                j += 1
        return ids, matrix

    def search(self, session: Session, query_vector: list[float], limit: int) -> dict[str, float]:
        """Return {passage_id: cosine similarity} for the nearest passages."""
        if _dialect(session) == "postgresql":
            rows = session.execute(
                text(
                    "SELECT id, 1 - (embedding <=> CAST(:v AS vector)) AS s FROM passages "
                    "WHERE embedding IS NOT NULL ORDER BY embedding <=> CAST(:v AS vector) LIMIT :n"
                ),
                {"v": str(list(query_vector)), "n": limit},
            )
            return {row.id: float(row.s) for row in rows}
        index = self._load(session)
        if not index.ids or index.matrix.shape[1] != len(query_vector):
            return {}
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        scores = index.matrix @ q
        k = min(limit, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        return {index.ids[i]: float(scores[i]) for i in top}


def reset_caches() -> None:
    """For tests and after bulk re-embedding."""
    _FTS_READY.clear()
    _MATRICES.clear()
