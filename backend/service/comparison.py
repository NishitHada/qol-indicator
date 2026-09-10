from __future__ import annotations

from dataclasses import dataclass

from domain.models import FactorResult, FactorStatus

# Scores are reported to one decimal place, so anything at or under this is noise
# dressed as a result. Declaring a winner by a tenth of a point would be exactly the
# false precision the rest of the scoring works to avoid.
TIE_THRESHOLD = 0.5


@dataclass(frozen=True)
class FactorComparison:
    label: str
    scores: list[float | None]
    winner: int | None
    difference: float | None


@dataclass(frozen=True)
class Comparison:
    overall_winner: int | None
    overall_difference: float
    factors: dict[str, FactorComparison]


def _best(scores: list[float | None]) -> tuple[int | None, float | None]:
    """(index of the clear winner, gap to the runner-up), or (None, gap) for a tie.

    Only locations whose factor actually resolved take part. A factor that failed for
    one location is not a loss for it - we do not know what it would have scored, so
    the honest answer is that the two cannot be compared on it, which is why the
    comparison reports a winner of None rather than handing the win to whoever we
    happened to have data for.
    """
    known = [(i, s) for i, s in enumerate(scores) if s is not None]
    if len(known) < 2:
        return None, None
    known.sort(key=lambda pair: pair[1], reverse=True)
    gap = known[0][1] - known[1][1]
    if gap <= TIE_THRESHOLD:
        return None, round(gap, 1)
    return known[0][0], round(gap, 1)


def compare(
    factor_results: list[dict[str, FactorResult]], overall_scores: list[float]
) -> Comparison:
    """Builds a factor-by-factor comparison across two or more scored locations.

    Kept out of the route so the same logic serves the HTTP API and anything else that
    grows on top of it later, and so it can be tested without a request.
    """
    if len(factor_results) != len(overall_scores):
        raise ValueError("one overall score is required per location")

    keys: list[str] = []
    for results in factor_results:
        for key in results:
            if key not in keys:
                keys.append(key)

    factors: dict[str, FactorComparison] = {}
    for key in keys:
        present = [r.get(key) for r in factor_results]
        label = next((p.label for p in present if p is not None), key)
        if any(p is not None and p.status == FactorStatus.COMING_SOON for p in present):
            continue  # nothing to compare on a factor nobody has implemented yet
        scores = [
            p.score if p is not None and p.status == FactorStatus.OK else None for p in present
        ]
        winner, difference = _best(scores)
        factors[key] = FactorComparison(
            label=label, scores=scores, winner=winner, difference=difference
        )

    overall_winner, overall_gap = _best(list(overall_scores))
    return Comparison(
        overall_winner=overall_winner,
        overall_difference=overall_gap if overall_gap is not None else 0.0,
        factors=factors,
    )
