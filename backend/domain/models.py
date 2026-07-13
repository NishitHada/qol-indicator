from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

# Any factor that could not be positively verified (not_found or error) is scored
# at this floor when computing the composite, never excluded/renormalized away.
# See "Scoring philosophy: no false positives" in the project plan.
UNVERIFIED_FLOOR_SCORE = 5.0


class FactorStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    ERROR = "error"
    COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class FactorResult:
    key: str
    label: str
    score: float | None
    raw_value: float | None
    unit: str | None
    status: FactorStatus
    source: str | None = None
    detail: str | None = None


FactorComputeFn = Callable[[float, float], Awaitable[FactorResult]]


@dataclass(frozen=True)
class VendorAdapter:
    name: str
    compute: FactorComputeFn


@dataclass(frozen=True)
class FactorDefinition:
    key: str
    label: str
    weight: float
    enabled: bool
    vendors: list[VendorAdapter]
