from __future__ import annotations

from domain.models import FactorResult, FactorStatus
from service.comparison import TIE_THRESHOLD, compare


def _ok(key, score, label=None):
    return FactorResult(
        key=key, label=label or key.title(), score=score, raw_value=None, unit=None,
        status=FactorStatus.OK,
    )


def _failed(key, label=None):
    return FactorResult(
        key=key, label=label or key.title(), score=None, raw_value=None, unit=None,
        status=FactorStatus.NOT_FOUND,
    )


def _stub(key):
    return FactorResult(
        key=key, label=key.title(), score=None, raw_value=None, unit=None,
        status=FactorStatus.COMING_SOON,
    )


def test_the_higher_score_wins_a_factor():
    result = compare([{"a": _ok("a", 80.0)}, {"a": _ok("a", 40.0)}], [80.0, 40.0])
    assert result.factors["a"].winner == 0
    assert result.factors["a"].difference == 40.0
    assert result.factors["a"].scores == [80.0, 40.0]


def test_the_second_location_can_win():
    result = compare([{"a": _ok("a", 10.0)}, {"a": _ok("a", 90.0)}], [10.0, 90.0])
    assert result.factors["a"].winner == 1
    assert result.overall_winner == 1


def test_a_difference_inside_the_tie_threshold_is_not_a_win():
    """Scores carry one decimal place. Calling a 0.2 gap a winner would be false
    precision, and this app's whole posture is against that."""
    result = compare([{"a": _ok("a", 70.2)}, {"a": _ok("a", 70.0)}], [70.2, 70.0])
    assert result.factors["a"].winner is None
    assert result.factors["a"].difference == 0.2
    assert result.overall_winner is None


def test_a_gap_just_past_the_threshold_is_a_win():
    b = 70.0
    a = b + TIE_THRESHOLD + 0.1
    result = compare([{"a": _ok("a", a)}, {"a": _ok("a", b)}], [a, b])
    assert result.factors["a"].winner == 0


def test_a_factor_that_failed_for_one_location_has_no_winner():
    """Not knowing what B would have scored is not the same as B scoring badly.
    Handing the win to whoever happened to have data would invent a result."""
    result = compare([{"a": _ok("a", 90.0)}, {"a": _failed("a")}], [90.0, 40.0])
    assert result.factors["a"].winner is None
    assert result.factors["a"].difference is None
    assert result.factors["a"].scores == [90.0, None]


def test_unimplemented_factors_are_left_out_entirely():
    result = compare([{"a": _ok("a", 50.0), "z": _stub("z")}, {"a": _ok("a", 10.0), "z": _stub("z")}], [50.0, 10.0])
    assert "z" not in result.factors
    assert "a" in result.factors


def test_a_factor_only_one_location_reported_is_still_listed_but_uncontested():
    result = compare([{"a": _ok("a", 50.0)}, {}], [50.0, 5.0])
    assert result.factors["a"].scores == [50.0, None]
    assert result.factors["a"].winner is None


def test_labels_come_from_whichever_location_has_them():
    result = compare([{}, {"a": _ok("a", 12.0, label="Greenery")}], [5.0, 12.0])
    assert result.factors["a"].label == "Greenery"


def test_more_than_two_locations_are_supported():
    results = [{"a": _ok("a", 30.0)}, {"a": _ok("a", 90.0)}, {"a": _ok("a", 60.0)}]
    comparison = compare(results, [30.0, 90.0, 60.0])
    assert comparison.factors["a"].winner == 1
    # The gap reported is to the runner-up, not to the worst.
    assert comparison.factors["a"].difference == 30.0
