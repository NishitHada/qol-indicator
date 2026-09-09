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


@dataclass(frozen=True)
class UserProfile:
    """Optional, freeform personalization input. Every field defaults to None/absent -
    a profile with nothing set behaves identically to no profile at all."""

    age: int | None = None


ProfilePredicate = Callable[[UserProfile], bool]


@dataclass(frozen=True)
class WeightAdjustmentRule:
    """Multiplies one factor's base weight when `applies(profile)` is true. Several
    rules can fire on the same factor (multipliers stack); the aggregator renormalizes
    all weights back to sum to 1.0 afterward, so this only ever shifts relative
    emphasis - it never changes what range the composite score can land in."""

    factor_key: str
    multiplier: float
    applies: ProfilePredicate
    reason: str
