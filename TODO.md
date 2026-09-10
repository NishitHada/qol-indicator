# Data sources still to integrate

Everything here is a factor the app knows about but does not yet score. It is ordered
by how hard the *data access* is, not by how hard the code is — the code is a new
module plus a registry entry in every case, and the four extension points in
[README.md](README.md#architecture) are unchanged.

Counts below are measured against the Bangalore OSM extract this repo builds from
(`scripts/build_bangalore_osm.py`), not estimated.

## Tier 1 — no new access needed

The data is already in the OpenStreetMap extract we download. These need a tag filter,
a scoring curve, and a rebuild of `data/bangalore_osm.json.gz`.

| Factor | What's mapped in Bangalore | Notes |
|---|---|---|
| **Road width & condition** (`road_quality`) | 8,745 tertiary + 3,998 secondary ways; `surface` on ~29k ways, of which **12,310 asphalt / 10,990 unpaved**; `lanes` on 4,653 | The unpaved count is the signal. Score the nearest road's class + surface + lane count. |
| **Walkability** (new factor) | 15,024 footways, 242 pedestrian ways, 184k residential streets | Sidewalk tagging is sparse (1,457 `sidewalk=no`), so this has to be footway *density* in a radius, not a per-street verdict. |
| **Locality premium-ness** (`locality_premium`) | — | See the poshness section below: built form does not measure this. Needs the guidance values in Tier 3. |
| **Flood risk** (new factor) | 2,630 drains, 140 ditches, plus SRTM elevation | A proxy, and should be labelled as one: drain proximity and local elevation relative to surroundings, not a hydrological model. Bangalore's flooding is real and this is the only free signal for it. |

## Tier 2 — free, but needs a signup key

Both were checked and both reject anonymous requests, so each needs an account before
any code is worth writing.

- **OpenAQ** (`https://api.openaq.org/v3`) — returns **HTTP 401** without a key.
  Register for a free key, send it as `X-API-Key`. This gives **real CPCB
  ground-station readings**, which is a materially better vendor for the existing
  `aqi` factor than the CAMS *model* output we use now. It slots in through
  `service/vendor_fallback.py` as a preferred vendor with Open-Meteo as the fallback,
  since station coverage is patchy and a model always answers.
- **data.gov.in** — returns **HTTP 403** on the demo key. Free registration gives a
  real key. Hosts CPCB realtime AQI plus a lot of other Indian government data worth
  surveying once there is a key to survey it with.

## Measuring "poshness" — investigated, partly resolved

Worth recording, because the obvious approach fails and the failure is not obvious.

The intuition is that bigger houses and lower density mean a more affluent area, and
that this is measurable from building footprints. **It is not, in Bangalore.** Tested
against twelve hand-picked areas using two independent datasets:

| Area | Median footprint | Buildings/ha | Built coverage |
|---|---|---|---|
| Dollars Colony (affluent) | 195 m² | 3.8 | 13% |
| Sadashivanagar (affluent) | 186 m² | 13.2 | 30% |
| D J Halli (informal) | 167 m² | 9.7 | 23% |
| Chickpet (dense old core) | 271 m² | 11.6 | 56% |

Chickpet has the largest median footprint of anything tested and is one of the most
crowded places in the city. All three metrics overlap between the affluent and the
poor groups, so no threshold ranks them correctly. Bangalore's built form simply does
not track income: old high-value commercial cores are dense, some informal settlements
are low-rise sprawl, and affluent areas contain both bungalow layouts and apartment
towers. Caveat on the test itself — twelve coordinates chosen from memory is thin
ground truth, though the overlap held across both datasets.

**Google Earth imagery cannot be used for this.** It is licensed from Maxar, Airbus and
CNES, and the Maps Platform terms prohibit bulk download, derived datasets, and
training models on the content. Google Earth Pro is a viewer licence; Google Earth
Engine is a separate product whose catalogue is open satellite data, not the
high-resolution basemap. The extraction that would have been attempted is already
published under a licence that permits it, which is what the `crowding` factor now uses.

What came out of this instead: the `crowding` factor, which measures built coverage as
open space and setbacks rather than as a proxy for income. For actual poshness, the
guidance values below remain the answer — they measure it directly.

## Tier 3 — public data, but no API

- **Price per m²** (`price_per_sqm`) and **locality premium-ness**
  (`locality_premium`). The property portals (MagicBricks, 99acres, NoBroker,
  Housing.com) all forbid scraping in their terms, which is why this is still a stub.
  The legal alternative is **Karnataka's guidance values** on the Kaveri portal
  (`kaverionline.karnataka.gov.in`) — official per-locality government rates, free, no
  login, and its `robots.txt` is empty. Two caveats worth being honest about: guidance
  value is a floor for stamp duty, not market price, and the portal is a form, not an
  API. Read its terms page before automating anything, given what the property portals
  turned out to say. Guidance values change roughly annually, so this suits the same
  bundle-at-build-time pattern as the OSM and climate data.

## Tier 4 — no source at the resolution this app scores at

Listed so the reasoning isn't re-derived later. Each of these would produce a number
that looks precise and isn't, which is the failure mode the whole scoring philosophy
is built to avoid.

- **Crime rate** (`crime_rate`) — NCRB publishes annual city and district totals as
  PDFs. This app scores at roughly 500m. A district-wide figure spread across every
  point in the district tells a user nothing about the street they're looking at.
- **Electricity availability** (`electricity_availability`) — BESCOM publishes outage
  notices, which are transient events, not a property of a locality. There is no
  reliability-by-area feed.
- **Drinking water** (`drinking_water`) — BWSSB supply schedules aren't published as
  data; CGWB groundwater quality is district-level, same resolution problem as crime.

## Surveyed and rejected

From [bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view). Each
is a fine source, just not for this city:

- **USGS earthquake feed** (keyless, global) — Karnataka is seismic Zone II, India's
  lowest. Revisit if the app ever covers another region.
- **NASA FIRMS active fires** (free key, global) — Bangalore has no recurring fire
  signal like Delhi's stubble burning.
- **TomTom live traffic flow** (free tier) — would be a genuinely better vendor for
  `noise_sources` than the OSM road-class baseline, since Bangalore's traffic noise is
  real and varies by time of day. Worth doing; just needs a key.
- **GBFS bikeshare feeds** — checked the official system registry: **zero GBFS systems
  exist in India**. Blocked, not deprioritised.

## Not data — product work

- **More ground-truth fixtures.** `backend/tests/test_ground_truth_bangalore.py` now
  pins 16 Bangalore locations, with relative orderings preferred over absolute values
  so a threshold tweak does not cause a false alarm. Seven injected regressions were
  all caught. Worth extending whenever a factor is added or a scoring curve changes;
  the two tables at the top of that file are the only things to edit.
- **Noise does not model street-level congestion.** Chickpet scores 96 and Peenya 100,
  meaning "quiet", because `noise_sources` only sees motorway/trunk/primary roads and
  airports. Both are in reality loud, from traffic on smaller streets and from horns
  and crowds. This is a false positive in the direction the scoring philosophy cares
  most about, so it is worth fixing. TomTom live traffic flow, already listed below,
  is the obvious vendor.
- **Commute time to a named work address** — extends `connectivity` from "is there
  transit" to "how long to your office". Needs a routing API (OpenRouteService has a
  free tier). This is also a prerequisite for Phase 1's natural-language queries.
- **Phase 1** — natural-language query parsing ("a 3BHK in a good locality within
  10km of my office, budget 50k/month").
- **Phase 2** — real-estate platform integration and affiliate links. Blocked on the
  terms-of-service problem described in Tier 3.
- **Phase 3** — expose the scorer as an MCP server so Claude can call it directly.
