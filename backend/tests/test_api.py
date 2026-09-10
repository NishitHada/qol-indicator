from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from domain.models import FactorResult, FactorStatus
from service import aggregator

BLR = (12.9716, 77.6046)
INDIRANAGAR = (12.9784, 77.6408)


@pytest.fixture
def client():
    return TestClient(create_app())


def _fake_factors(scores: dict[str, float | None]) -> dict[str, FactorResult]:
    out = {}
    for key, score in scores.items():
        out[key] = FactorResult(
            key=key,
            label=key.replace("_", " ").title(),
            score=score,
            raw_value=None,
            unit=None,
            status=FactorStatus.OK if score is not None else FactorStatus.NOT_FOUND,
        )
    return out


@pytest.fixture
def stub_scoring(monkeypatch):
    """Replaces the aggregator so the API tests exercise the HTTP layer rather than
    the scoring pipeline, which has its own tests and one live upstream."""
    by_point: dict[tuple[float, float], dict[str, FactorResult]] = {}

    async def fake_compute_all(lat, lng, profile=None):
        return by_point[(round(lat, 5), round(lng, 5))]

    def register(lat, lng, scores):
        by_point[(round(lat, 5), round(lng, 5))] = _fake_factors(scores)

    monkeypatch.setattr(aggregator, "compute_all", fake_compute_all)
    monkeypatch.setattr(
        aggregator,
        "compute_overall",
        lambda results, profile=None: aggregator.OverallScore(
            score=round(sum(r.score or 0 for r in results.values()) / max(len(results), 1), 1),
            weights_used={k: 1 / len(results) for k in results},
            unverified=[k for k, r in results.items() if r.score is None],
            personalization_applied=[],
            excluded=[],
        ),
    )
    return register


def test_compare_reports_a_winner_per_factor(client, stub_scoring):
    stub_scoring(*BLR, {"greenery_proximity": 90.0, "crowding": 20.0})
    stub_scoring(*INDIRANAGAR, {"greenery_proximity": 30.0, "crowding": 80.0})

    res = client.post(
        "/api/compare",
        json={"locations": [{"lat": BLR[0], "lng": BLR[1]}, {"lat": INDIRANAGAR[0], "lng": INDIRANAGAR[1]}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["factors"]["greenery_proximity"]["winner"] == 0
    assert body["factors"]["crowding"]["winner"] == 1
    assert body["factors"]["crowding"]["difference"] == 60.0
    assert len(body["locations"]) == 2


def test_compare_locations_come_back_in_request_order(client, stub_scoring):
    stub_scoring(*BLR, {"a": 10.0})
    stub_scoring(*INDIRANAGAR, {"a": 90.0})
    res = client.post(
        "/api/compare",
        json={"locations": [{"lat": INDIRANAGAR[0], "lng": INDIRANAGAR[1]}, {"lat": BLR[0], "lng": BLR[1]}]},
    )
    body = res.json()
    assert body["locations"][0]["location"]["lat"] == pytest.approx(INDIRANAGAR[0])
    assert body["overall_winner"] == 0


def test_compare_rejects_a_single_location(client):
    res = client.post("/api/compare", json={"locations": [{"lat": BLR[0], "lng": BLR[1]}]})
    assert res.status_code == 422


def test_compare_rejects_more_than_four_locations(client):
    locations = [{"lat": 12.9 + i / 100, "lng": 77.6} for i in range(5)]
    assert client.post("/api/compare", json={"locations": locations}).status_code == 422


def test_share_round_trips_through_the_api(client):
    created = client.post(
        "/api/share",
        json={
            "locations": [{"lat": BLR[0], "lng": BLR[1]}, {"lat": INDIRANAGAR[0], "lng": INDIRANAGAR[1]}],
            "profile": {"age": 68},
        },
    )
    assert created.status_code == 200
    code = created.json()["code"]

    resolved = client.get(f"/api/share/{code}")
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["locations"][0]["lat"] == pytest.approx(BLR[0], abs=1e-5)
    assert body["locations"][1]["lng"] == pytest.approx(INDIRANAGAR[1], abs=1e-5)
    assert body["profile"]["age"] == 68


def test_share_without_a_profile_resolves_without_one(client):
    code = client.post("/api/share", json={"locations": [{"lat": BLR[0], "lng": BLR[1]}]}).json()["code"]
    assert client.get(f"/api/share/{code}").json()["profile"] is None


def test_an_unknown_share_code_is_a_404_not_a_crash(client):
    assert client.get("/api/share/not-a-real-code").status_code == 404


def test_share_codes_are_stable_for_the_same_input(client):
    """The code is derived from the payload, not stored, so the same view always
    produces the same link - two people sharing the same place get one URL."""
    body = {"locations": [{"lat": BLR[0], "lng": BLR[1]}], "profile": {"age": 30}}
    first = client.post("/api/share", json=body).json()["code"]
    second = client.post("/api/share", json=body).json()["code"]
    assert first == second


def test_a_share_link_survives_a_restart(client):
    """The point of a stateless code: a link created by one process resolves in a
    completely fresh one, with no shared storage between them."""
    code = client.post("/api/share", json={"locations": [{"lat": BLR[0], "lng": BLR[1]}]}).json()["code"]
    fresh = TestClient(create_app())
    assert fresh.get(f"/api/share/{code}").status_code == 200


def test_score_still_works_unchanged(client, stub_scoring):
    stub_scoring(*BLR, {"a": 50.0})
    res = client.post("/api/score", json={"lat": BLR[0], "lng": BLR[1]})
    assert res.status_code == 200
    assert res.json()["overall_score"] == 50.0
