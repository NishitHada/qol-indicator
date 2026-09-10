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
# Some factors do not just get *weighted* differently for a profile - they measure
# something different. Religious site proximity means places of worship of the user's
# own faith; transport connectivity means the mode they actually use. Those take the
# profile as a third argument and declare it on their VendorAdapter.
ProfileAwareComputeFn = Callable[[float, float, "UserProfile | None"], Awaitable[FactorResult]]


@dataclass(frozen=True)
class VendorAdapter:
    name: str
    compute: FactorComputeFn | ProfileAwareComputeFn
    # Explicit rather than inferred from the signature: which factors respond to a
    # profile is a design fact worth reading off the registry, not something to
    # discover by introspection at call time.
    profile_aware: bool = False


@dataclass(frozen=True)
class FactorDefinition:
    key: str
    label: str
    weight: float
    enabled: bool
    vendors: list[VendorAdapter]


class Religion(str, Enum):
    """Values are OpenStreetMap's own `religion=*` tag values, so a profile can be
    matched against map data without a translation table. 96.9% of Bangalore's 3,206
    mapped places of worship carry this tag, which is what makes filtering on it
    worthwhile at all."""

    HINDU = "hindu"
    MUSLIM = "muslim"
    CHRISTIAN = "christian"
    JAIN = "jain"
    SIKH = "sikh"
    BUDDHIST = "buddhist"
    JEWISH = "jewish"


class TransportPreference(str, Enum):
    METRO = "metro"
    BUS = "bus"
    CAB = "cab"


@dataclass(frozen=True)
class UserProfile:
    """Optional, freeform personalization input. Every field defaults to None/absent -
    a profile with nothing set behaves identically to no profile at all, and each
    field is independent of the others."""

    age: int | None = None
    # Restricts religious site proximity to places of worship of this faith.
    religion: Religion | None = None
    # Restricts transport connectivity to the mode actually used. CAB drops the factor
    # from the composite entirely - someone who always takes a cab is not served or
    # underserved by a nearby bus stop, so scoring them on it would be noise.
    transport_preference: TransportPreference | None = None

    def is_empty(self) -> bool:
        return self.age is None and self.religion is None and self.transport_preference is None


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
