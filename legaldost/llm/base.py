"""Provider-neutral LLM interface, usage accounting and budget enforcement."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from legaldost.db.models import UsageRecord

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Tier = Literal["router", "standard", "deep"]

# USD per million tokens (input, output). Source: Anthropic model table as cached in the
# claude-api reference on 2026-10-06. Verify against the current pricing page before relying on it.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


class LLMError(Exception):
    """Base class. ``retryable`` tells callers whether a later attempt may succeed."""

    retryable = False


class LLMUnavailable(LLMError):
    retryable = True


class LLMRefused(LLMError):
    pass


class LLMBadOutput(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class LLMResult(Generic[T]):
    output: T
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


class LLMProvider(Protocol):
    name: str

    def structured(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> LLMResult[T]: ...


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


class UsageLedger:
    """Records every provider call and enforces the monthly budget and per-question call cap."""

    def __init__(self, session: Session, monthly_budget_usd: float, max_calls_per_question: int) -> None:
        self.session = session
        self.monthly_budget_usd = monthly_budget_usd
        self.max_calls_per_question = max_calls_per_question
        self.calls_this_question = 0

    def month_spend(self) -> float:
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        total = self.session.scalar(
            select(func.sum(UsageRecord.cost_usd)).where(UsageRecord.created_at >= start)
        )
        return float(total or 0.0)

    def check(self) -> None:
        if self.calls_this_question >= self.max_calls_per_question:
            raise BudgetExceeded("per-question model call limit reached")
        if self.monthly_budget_usd > 0 and self.month_spend() >= self.monthly_budget_usd:
            raise BudgetExceeded("monthly LLM budget reached")

    def record(
        self,
        provider: str,
        model: str,
        purpose: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        success: bool = True,
        error_type: str | None = None,
    ) -> None:
        self.calls_this_question += 1
        self.session.add(
            UsageRecord(
                provider=provider,
                model=model,
                purpose=purpose,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                success=success,
                error_type=error_type,
            )
        )


class MeteredLLM:
    """Wraps a provider with budget checks and usage recording."""

    def __init__(self, provider: LLMProvider, ledger: UsageLedger) -> None:
        self.provider = provider
        self.ledger = ledger

    @property
    def name(self) -> str:
        return self.provider.name

    def structured(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> LLMResult[T]:
        self.ledger.check()
        try:
            result = self.provider.structured(
                purpose=purpose, tier=tier, system=system, user=user, schema=schema, max_tokens=max_tokens
            )
        except LLMError as exc:
            self.ledger.record(
                self.provider.name, tier, purpose, success=False, error_type=type(exc).__name__
            )
            raise
        self.ledger.record(
            self.provider.name,
            result.model,
            purpose,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        )
        return result
