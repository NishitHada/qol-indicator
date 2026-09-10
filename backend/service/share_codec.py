from __future__ import annotations

import base64
from dataclasses import dataclass

# A share link carries its whole payload in the code itself rather than pointing at a
# stored row. That means no database, no cleanup job, and - the part that actually
# matters - a link that cannot rot: there is no row to expire or lose when the free
# tier restarts and wipes the disk. The cost is that the code grows with the payload,
# which is fine for one or two coordinates and a number.

VERSION = 2
_VERSION_BITS = 4
_COUNT_BITS = 2  # 1-4 locations
_AGE_BITS = 7  # 0-120, matching the profile schema's bound
_RELIGION_BITS = 4
_TRANSPORT_BITS = 2

# Explicit ordered lists, not the enums' own iteration order: these indices are
# baked into every link ever generated, so reordering or removing an enum member
# must not change what an existing code decodes to. Append only.
_RELIGIONS = ("hindu", "muslim", "christian", "jain", "sikh", "buddhist", "jewish")
_TRANSPORT = ("metro", "bus", "cab")

# ~1.1m. Finer than anything the scoring resolves, and coarse enough to keep the code
# short. Latitude spans 180 degrees and longitude 360, hence the different widths.
_SCALE = 100_000
_LAT_BITS = 25  # (90 + 90) * 100_000 = 18,000,000 < 2**25
_LNG_BITS = 26  # (180 + 180) * 100_000 = 36,000,000 < 2**26

MAX_LOCATIONS = 2**_COUNT_BITS


class ShareCodeError(ValueError):
    """The code is not something this version can decode."""


@dataclass(frozen=True)
class SharePayload:
    locations: list[tuple[float, float]]
    age: int | None = None
    religion: str | None = None
    transport_preference: str | None = None


class _BitReader:
    def __init__(self, value: int, total_bits: int):
        self._value = value
        self._remaining = total_bits

    def take(self, count: int) -> int:
        if count > self._remaining:
            raise ShareCodeError("share code is truncated")
        self._remaining -= count
        return (self._value >> self._remaining) & ((1 << count) - 1)


def encode(payload: SharePayload) -> str:
    if not payload.locations:
        raise ShareCodeError("a share code needs at least one location")
    if len(payload.locations) > MAX_LOCATIONS:
        raise ShareCodeError(f"a share code holds at most {MAX_LOCATIONS} locations")

    religion_index = _index_of(payload.religion, _RELIGIONS, "religion")
    transport_index = _index_of(payload.transport_preference, _TRANSPORT, "transport preference")

    # The leading 1 is a sentinel. Without it a payload that happens to start with
    # zero bits would lose them to the integer, and the decoder could not tell how
    # long the field run was meant to be.
    bits = 1
    bits = (bits << _VERSION_BITS) | VERSION
    bits = (bits << 1) | (1 if payload.age is not None else 0)
    bits = (bits << 1) | (1 if religion_index is not None else 0)
    bits = (bits << 1) | (1 if transport_index is not None else 0)
    bits = (bits << _COUNT_BITS) | (len(payload.locations) - 1)
    for lat, lng in payload.locations:
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ShareCodeError("coordinates out of range")
        bits = (bits << _LAT_BITS) | round((lat + 90) * _SCALE)
        bits = (bits << _LNG_BITS) | round((lng + 180) * _SCALE)
    if payload.age is not None:
        if not (0 <= payload.age < 2**_AGE_BITS):
            raise ShareCodeError("age out of range")
        bits = (bits << _AGE_BITS) | payload.age
    if religion_index is not None:
        bits = (bits << _RELIGION_BITS) | religion_index
    if transport_index is not None:
        bits = (bits << _TRANSPORT_BITS) | transport_index

    raw = bits.to_bytes((bits.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _index_of(value: str | None, table: tuple[str, ...], what: str) -> int | None:
    if value is None:
        return None
    try:
        return table.index(value)
    except ValueError as e:
        raise ShareCodeError(f"unknown {what} {value!r}") from e


def decode(code: str) -> SharePayload:
    if not code or len(code) > 64:
        raise ShareCodeError("not a share code")
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    except Exception as e:
        raise ShareCodeError("not a share code") from e
    if not raw:
        raise ShareCodeError("not a share code")

    bits = int.from_bytes(raw, "big")
    reader = _BitReader(bits, bits.bit_length() - 1)  # drop the sentinel

    version = reader.take(_VERSION_BITS)
    if version not in (1, 2):
        raise ShareCodeError(f"unsupported share code version {version}")

    # Version 1 predates the religion and transport fields. Links handed out under it
    # still work - which is the entire reason the format carries a version at all.
    has_age = bool(reader.take(1))
    has_religion = bool(reader.take(1)) if version >= 2 else False
    has_transport = bool(reader.take(1)) if version >= 2 else False

    count = reader.take(_COUNT_BITS) + 1
    locations = []
    for _ in range(count):
        lat = reader.take(_LAT_BITS) / _SCALE - 90
        lng = reader.take(_LNG_BITS) / _SCALE - 180
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ShareCodeError("share code decodes to an impossible location")
        locations.append((round(lat, 5), round(lng, 5)))

    age = reader.take(_AGE_BITS) if has_age else None
    religion = _value_at(reader.take(_RELIGION_BITS), _RELIGIONS, "religion") if has_religion else None
    transport = (
        _value_at(reader.take(_TRANSPORT_BITS), _TRANSPORT, "transport preference")
        if has_transport
        else None
    )
    return SharePayload(
        locations=locations, age=age, religion=religion, transport_preference=transport
    )


def _value_at(index: int, table: tuple[str, ...], what: str) -> str:
    if index >= len(table):
        raise ShareCodeError(f"share code names an unknown {what}")
    return table[index]
