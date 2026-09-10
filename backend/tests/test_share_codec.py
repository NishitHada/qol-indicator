from __future__ import annotations

import pytest

from service.share_codec import MAX_LOCATIONS, ShareCodeError, SharePayload, decode, encode

BLR = (12.9716, 77.6046)
INDIRANAGAR = (12.9784, 77.6408)


def test_a_single_location_round_trips():
    payload = SharePayload(locations=[BLR])
    decoded = decode(encode(payload))
    assert decoded.locations == [BLR]
    assert decoded.age is None


def test_two_locations_and_an_age_round_trip():
    payload = SharePayload(locations=[BLR, INDIRANAGAR], age=68)
    decoded = decode(encode(payload))
    assert decoded.locations == [BLR, INDIRANAGAR]
    assert decoded.age == 68


def test_location_order_is_preserved():
    """A comparison of A against B is not the same page as B against A."""
    forward = decode(encode(SharePayload(locations=[BLR, INDIRANAGAR])))
    backward = decode(encode(SharePayload(locations=[INDIRANAGAR, BLR])))
    assert forward.locations == [BLR, INDIRANAGAR]
    assert backward.locations == [INDIRANAGAR, BLR]


def test_a_single_location_code_is_short_enough_to_paste():
    code = encode(SharePayload(locations=[BLR]))
    assert len(code) <= 12, code


def test_codes_are_url_safe():
    for lat, lng in [BLR, (-33.8688, 151.2093), (0.0, 0.0), (-89.9, -179.9), (89.9, 179.9)]:
        code = encode(SharePayload(locations=[(lat, lng)], age=30))
        assert all(c.isalnum() or c in "-_" for c in code), code


@pytest.mark.parametrize(
    "point",
    [(0.0, 0.0), (90.0, 180.0), (-90.0, -180.0), (12.97161, 77.60459), (-33.86882, 151.20930)],
)
def test_coordinates_survive_to_about_a_metre(point):
    decoded = decode(encode(SharePayload(locations=[point])))
    lat, lng = decoded.locations[0]
    assert abs(lat - point[0]) < 1e-5
    assert abs(lng - point[1]) < 1e-5


def test_age_zero_is_kept_rather_than_treated_as_absent():
    """0 is falsy in every language this payload passes through, so it is the value
    most likely to be silently dropped."""
    assert decode(encode(SharePayload(locations=[BLR], age=0))).age == 0


def _spread(count: int) -> list[tuple[float, float]]:
    # Written out at 5dp rather than accumulated, so the test compares against exact
    # values instead of whatever float addition produced.
    return [(round(12.90 + i / 100, 5), round(77.60 + i / 100, 5)) for i in range(count)]


def test_the_maximum_number_of_locations_round_trips():
    points = _spread(MAX_LOCATIONS)
    assert decode(encode(SharePayload(locations=points))).locations == points


def test_too_many_locations_is_rejected_at_encode_time():
    points = _spread(MAX_LOCATIONS + 1)
    with pytest.raises(ShareCodeError):
        encode(SharePayload(locations=points))


def test_no_locations_is_rejected():
    with pytest.raises(ShareCodeError):
        encode(SharePayload(locations=[]))


@pytest.mark.parametrize("bad", ["", "!!!!", "a" * 200, "////", "z"])
def test_garbage_is_rejected_rather_than_decoded_into_a_location(bad):
    with pytest.raises(ShareCodeError):
        decode(bad)


def test_a_future_version_is_refused_by_name():
    """The version field exists so a format change can add a branch instead of
    silently decoding old codes into the wrong coordinates."""
    from service import share_codec

    original = share_codec.VERSION
    try:
        share_codec.VERSION = 9
        future = encode(SharePayload(locations=[BLR]))
    finally:
        share_codec.VERSION = original
    with pytest.raises(ShareCodeError, match="version 9"):
        decode(future)


# Codes handed out before religion and transport preference existed. Hardcoded rather
# than regenerated, because the point is that bytes produced by the *old* encoder still
# decode - a test that re-encodes with today's code would prove nothing.
V1_SINGLE = "BEJ0fSGJEsw"
V1_TWO_WITH_AGE = "EanTNcYkHoE6PIjEg9BE"


def test_version_1_links_still_resolve():
    single = decode(V1_SINGLE)
    assert single.locations == [BLR]
    assert single.age is None

    both = decode(V1_TWO_WITH_AGE)
    assert both.locations == [(13.023, 77.576), (12.969, 77.576)]
    assert both.age == 68


def test_version_1_links_decode_with_the_new_fields_empty():
    """Not just "does not crash" - an old link must not acquire a faith or a travel
    preference its author never set."""
    payload = decode(V1_TWO_WITH_AGE)
    assert payload.religion is None
    assert payload.transport_preference is None


def test_religion_and_transport_round_trip():
    payload = SharePayload(
        locations=[BLR], age=68, religion="jain", transport_preference="metro"
    )
    decoded = decode(encode(payload))
    assert decoded.religion == "jain"
    assert decoded.transport_preference == "metro"
    assert decoded.age == 68


def test_each_profile_field_is_independent():
    only_religion = decode(encode(SharePayload(locations=[BLR], religion="sikh")))
    assert only_religion.religion == "sikh"
    assert only_religion.age is None and only_religion.transport_preference is None

    only_transport = decode(encode(SharePayload(locations=[BLR], transport_preference="cab")))
    assert only_transport.transport_preference == "cab"
    assert only_transport.age is None and only_transport.religion is None


def test_every_religion_and_transport_value_round_trips():
    """These are index-encoded, so a reordering of the tables would silently change
    what existing links mean."""
    from domain.models import Religion, TransportPreference

    for religion in Religion:
        assert decode(encode(SharePayload(locations=[BLR], religion=religion.value))).religion == religion.value
    for preference in TransportPreference:
        decoded = decode(encode(SharePayload(locations=[BLR], transport_preference=preference.value)))
        assert decoded.transport_preference == preference.value


def test_an_unknown_religion_is_refused_rather_than_silently_dropped():
    with pytest.raises(ShareCodeError, match="religion"):
        encode(SharePayload(locations=[BLR], religion="pastafarian"))
