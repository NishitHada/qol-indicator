from __future__ import annotations

import base64
from dataclasses import dataclass

# A share link carries its whole payload in the code itself rather than pointing at a
# stored row. That means no database, no cleanup job, and - the part that actually
# matters - a link that cannot rot: there is no row to expire or lose when the free
# tier restarts and wipes the disk. The cost is that the code grows with the payload,
# which is fine for one or two coordinates and a number.

VERSION = 1
_VERSION_BITS = 4
_COUNT_BITS = 2  # 1-4 locations
_AGE_BITS = 7  # 0-120, matching the profile schema's bound

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

    # The leading 1 is a sentinel. Without it a payload that happens to start with
    # zero bits would lose them to the integer, and the decoder could not tell how
    # long the field run was meant to be.
    bits = 1
    bits = (bits << _VERSION_BITS) | VERSION
    bits = (bits << 1) | (1 if payload.age is not None else 0)
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

    raw = bits.to_bytes((bits.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


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
    if version != VERSION:
        # Old links must keep working, so a future format change adds a branch here
        # rather than changing what VERSION 1 means.
        raise ShareCodeError(f"unsupported share code version {version}")

    has_age = bool(reader.take(1))
    count = reader.take(_COUNT_BITS) + 1
    locations = []
    for _ in range(count):
        lat = reader.take(_LAT_BITS) / _SCALE - 90
        lng = reader.take(_LNG_BITS) / _SCALE - 180
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ShareCodeError("share code decodes to an impossible location")
        locations.append((round(lat, 5), round(lng, 5)))
    age = reader.take(_AGE_BITS) if has_age else None
    return SharePayload(locations=locations, age=age)
