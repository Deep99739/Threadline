"""Synthetic queue runner containing an intentionally unused retry policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25

    def delays(self) -> tuple[float, ...]:
        return tuple(
            self.base_delay_seconds * 2**attempt for attempt in range(self.max_attempts - 1)
        )


def run_job[Result](operation: Callable[[str], Result], idempotency_key: str) -> Result:
    """Run once; retry integration is intentionally absent in the initial fixture."""

    return operation(idempotency_key)
