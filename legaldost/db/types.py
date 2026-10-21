"""Dialect-aware column types."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class EmbeddingVector(TypeDecorator[list[float]]):
    """pgvector ``vector(n)`` on PostgreSQL, JSON array elsewhere (SQLite dev/tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            from legaldost.config import get_settings

            return dialect.type_descriptor(Vector(get_settings().embedding_dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        return [float(x) for x in value]
