# Quality of Life Indicator

Drop a pin (or search an address) on a Google Map and get a composite "quality of life"
score plus a factor-by-factor breakdown for that location.

## Architecture

```
frontend/ (React + Vite, Google Maps)          backend/ (FastAPI)
  MapView ──click / address search──►  POST /api/score {lat, lng, profile?}
  ScorePanel ◄──────────────────────  {overall_score, factors{}, weights_used,
                                        unverified_factors, personalization_applied}
```

Inside the backend, one request fans out like this:

```
api/routes.py
   └─ service/aggregator.py
        ├─ overpass_batch.compute_categories()   greenery, water, healthcare,
        │     ├─ local_osm  (bundled, no network)   social hub, religious site
        │     └─ Overpass mirrors (fallback, outside the bundled area)
        ├─ vendor_fallback.resolve() per remaining factor
        │     ├─ osm_lookup.nearby()  bundled-first OSM reads, shared by:
        │     │     ├─ connectivity       metro / rail / bus, best mode wins
        │     │     ├─ daily_essentials   groceries, pharmacy, school, banking
        │     │     ├─ pollution_sources  landfill, sewage, quarry, industry
        │     │     └─ noise_sources      roads/airports + adsb.lol live flights
        │     ├─ crowding          local_buildings (bundled, no live vendor)
        │     ├─ temperature       local_climate (bundled) → Open-Meteo archive
        │     ├─ wind_ventilation  local_climate (bundled) → Open-Meteo archive
        │     └─ aqi               Open-Meteo air-quality (365-day window)
        └─ compute_overall() → weights (× personalization) → composite score
```

**Data sources, and why each lives where it does:**

| Factor | Source | Bundled? |
|---|---|---|
| Greenery, water, healthcare, social hub, religious site | OpenStreetMap | ✅ `data/bangalore_osm.json.gz` |
| Connectivity, daily essentials, pollution sources, bad odour | OpenStreetMap | ✅ same file |
| Noise sources | OSM roads/airports + adsb.lol live flights | ✅ (OSM part) / live (flights) |
| Crowding & open space | Microsoft Global ML Building Footprints | ✅ `data/bangalore_buildings.json.gz` |
| Temperature, wind / ventilation | Open-Meteo archive (ERA5) | ✅ `data/bangalore_climate.json.gz` |
| Air quality | Open-Meteo air-quality (CAMS) | live, ~11km cache |

Everything static is bundled because **the public Overpass cluster and Open-Meteo's
archive API both refuse or throttle cloud provider IPs** — verified from Render's
outbound IP, where Overpass returns connection-refused and the archive returns 429,
while both serve the identical requests fine from an ordinary machine. That is why
production used to resolve only 2 of 8 factors. Parks, lakes and last year's weather
don't change between requests, so none of them belonged behind a live API call.

Four extension points, all declarative:

- **`service/registry.py`** — the factor list. Adding a factor is a new entry plus a
  `compute(lat, lng)`; the aggregator and frontend need no changes.
- **`service/overpass_categories.py`** — tags, radii and scoring curve per OSM category.
- **`service/personalization.py`** — profile → weight-adjustment rules.
- **`service/vendor_fallback.py`** — multiple providers per factor, tried in order.

A fifth is shared rather than declarative: **`service/osm_lookup.py`** is the one place
that decides bundled-vs-network for any factor reading OSM features, so a new one gets
that behaviour for free.

## Scored factors (14, live)

- Greenery proximity (OpenStreetMap Overpass)
- Water proximity (OpenStreetMap Overpass)
- Air quality / AQI (Open-Meteo) — a **365-day window**, not a live snapshot: the
  score is `avg AQI over the year, penalized for how many days crossed into
  "unhealthy or worse"`. A single clear (or single bad) day no longer swings the
  score; see `service/air_quality.py`.
- Temperature: average & extremes over a 365-day window (Open-Meteo ERA5, bundled -
  see below). Scored on a comfort band, penalized by how many days were extreme.
- Noise sources (OpenStreetMap Overpass — major roads & airports, + adsb.lol live
  low-altitude flight positions). Unlike the proximity factors above, being *close*
  to a road/airport/aircraft scores *low* (loud), not high — see
  `service/noise_sources.py`. Confirmed nothing nearby is scored as a verified
  "quiet" `100`, not floored as unverified, since absence of noise sources here is
  the good outcome.
- Healthcare proximity, social hub proximity (bars/cafés/nightlife/malls), and
  religious site proximity — all OpenStreetMap Overpass. These three use an
  **inverted-U ("sweet spot") curve** (`infra.geo.score_sweet_spot`), not "closer is
  always better": being immediately adjacent to a nightclub, a hospital, or a place
  of worship is a real downside (noise, sirens, crowds), not a bonus. Only
  greenery/water stay on the monotonic "closer is better" curve
  (`infra.geo.score_from_distance_decay`) - there's no plausible downside to being
  near a park.

- **Public transport connectivity** (OSM). Metro, suburban rail, bus interchanges and
  bus stops, each with its own walkable radius. Two decisions matter here. The best
  mode wins rather than an average, because a metro station 400m away makes a location
  well-connected however far the nearest bus stop is. And each mode has a **ceiling on
  what it can certify alone**: only metro reaches 100, a bus stop caps at 65. OSM
  records that a stop exists, not that it is usefully served, and BMTC frequencies vary
  enormously by route — so a lone mapped bus stop is real evidence of *some* access and
  not evidence of a well-connected address. See `service/connectivity.py`.
- **Daily essentials nearby** (OSM). Groceries, pharmacy, school and banking, scored as
  four separate errands and averaged. A missing errand scores zero rather than dropping
  out of the average: twenty supermarkets and no pharmacy is not a well-served location,
  and averaging only over what was found would score it 100. Distances use a plateau
  curve (`infra.geo.score_within_walk`) — 80m and 300m to a supermarket are the same
  errand, so scoring them 30 points apart would be false precision.
- **Pollution sources** and **bad odour** (OSM). Landfills, sewage plants, quarries,
  industrial estates and waste depots, scored on inverted decay like noise, with the
  worst source deciding rather than the nearest. Odour is a deliberately narrower set:
  an industrial estate degrades air quality without necessarily smelling, while a
  landfill is smelled kilometres away. Each source's penalty is scaled by its **mapped
  footprint** — Bangalore mandates a sewage treatment plant in every large apartment
  complex, and treating a shed-sized unit like a municipal plant was scoring Cubbon Park
  at 53. Size only ever *reduces* a penalty and only on proof: an unmapped footprint is
  treated as full-scale, so missing data can never talk the app into approving a
  location it should have flagged.
- **Crowding & open space** (Microsoft Global ML Building Footprints, bundled). The
  share of the ground covered by building footprints in a ~660m square, which is a
  direct measure of setbacks, light and air. Two things make this trustworthy where
  OpenStreetMap's own buildings would not be. The dataset is machine-extracted
  uniformly, so an empty area means open land rather than an area nobody has mapped —
  OSM building detail tracks mapping effort, and mapping effort tracks affluence, so
  OSM building statistics are biased in exactly the direction that would matter here.
  And footprint area is split across every cell a building overlaps rather than dumped
  on its centroid's cell, which is what previously produced a cell claiming 115% built
  coverage. Height is unavailable for India in this dataset, so this sees ground
  coverage only: a tower reads the same as a bungalow of equal footprint. There is no
  live vendor, so outside the bundled area the factor reports unverified rather than
  guessing. See `service/crowding.py`.
- **Wind / cross-ventilation** (Open-Meteo ERA5, bundled). Two components: average daily
  peak wind speed, and how evenly the year's wind is spread across the eight compass
  sectors. The second is the half that speed alone cannot express — cross-ventilation
  needs air to enter one side of a flat and leave the other, so a location whose wind
  arrives from one sector all year ventilates only the flats that happen to face it.
  This is a regional reading at ERA5's ~25km resolution, so it describes the wind
  arriving at the neighbourhood and cannot see whether the next building blocks it.

Six factors remain registered as stubs (`status: "coming_soon"`) so they can be
implemented without touching the aggregator or the frontend: crime rate, locality
premium-ness, road quality, drinking water, electricity availability, and price per m².
**[TODO.md](TODO.md) says what data each one is waiting on and how to get access**,
including which sources were surveyed and rejected, and why.

### Personalization (optional)

`POST /api/score` accepts an optional `profile: { age }`. With no profile (or an
empty one), the score is computed with the registry's base weights, unchanged -
personalization is opt-in, never mandatory. With a profile, `service/personalization.py`
applies matching rules (e.g. age ≤ 30 boosts `social_hub_proximity` and
`connectivity`; age 60+ boosts `healthcare_proximity`, `religious_site_proximity`,
`daily_essentials`, and `aqi`) as weight multipliers,
then renormalizes every enabled factor's weight back to sum to 1.0 - so personalization
only ever shifts relative emphasis between factors, never the 0-100 range of the
result or the floor-on-failure behavior. The response's `personalization_applied`
lists which rules actually fired, and the frontend surfaces that as a note under the
score. The rule table is declarative and additive, the same spirit as
`FACTOR_REGISTRY` - a new personalization dimension (e.g. `has_children`) means
adding rules, not restructuring the aggregator.

### Bundled data (the important one)

Three datasets ship with the app and cover the same Bangalore bounding box
(12.70–13.25 N, 77.30–77.90 E). Inside it, thirteen of the fourteen factors need **no
network call at all** — everything except live air quality:

| File | Size | Contents | Serves |
|---|---|---|---|
| `backend/data/bangalore_osm.json.gz` | 0.7 MB | 48,022 OSM features, 14,113 with a footprint area | greenery, water, healthcare, social hub, religious site, roads/airports, transit stops, shops/schools/banks, pollution sources |
| `backend/data/bangalore_buildings.json.gz` | 0.41 MB | 45,027 cells of ~220m over 1,030,477 building footprints | crowding & open space |
| `backend/data/bangalore_climate.json.gz` | 0.10 MB | 42-point grid × 366 days of temperature and wind | temperature, wind / ventilation |

These exist because **both upstreams block or throttle cloud provider IPs.** Verified
from Render's outbound IP: every Overpass mirror returns connection-refused, and
Open-Meteo's archive returns `429` — while both serve the identical requests fine from
an ordinary machine. That is why production resolved only AQI and temperature at
first, then only 7/8. No amount of mirror failover, batching or cache tuning fixes an
endpoint that won't accept your IP.

It's also simply the right design. Parks and lakes don't move, and last year's weather
is settled history — neither belonged behind a per-request API call. Measured on a
real Bangalore point: **14/14 factors in ~0.2s**, versus 2/8 in 30–55s before.

Both bundles store *raw inputs*, not precomputed scores, so all scoring logic stays in
the factor modules and behaves identically whether the data came from the bundle or
the network. Changing a scoring threshold does not require rebuilding them.

Regenerate:

```bash
cd backend

# OSM features (needs osmium-tool)
brew install osmium-tool
mkdir -p /tmp/osmbuild && curl -L -o /tmp/osmbuild/southern-zone.osm.pbf \
  https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
python3 scripts/build_bangalore_osm.py      # --rebuild to redo the osmium steps

# Climate grid (stdlib only; run from a machine that isn't rate-limited)
python3 scripts/build_bangalore_climate.py

# Building-density grid (stdlib only; downloads ~110 MB of tiles)
python3 scripts/build_bangalore_buildings.py
```

Points outside the bundled bounds fall back to the network paths described below. To
cover another city, widen the bbox in both scripts and re-run them.

### Overpass batching (the network fallback path)

Nine factors read OSM features. Inside the bundled area none of them touch the network;
outside it, this is the path they take.

The five plain proximity categories (greenery, water, healthcare, social hub, religious
site) go through `service/overpass_batch.py`, which fetches and caches features per
~550m grid cell so panning around a neighbourhood costs one fetch rather than one per
click. `service/overpass_categories.py` holds each category's tags, radius and scoring
curve — the single source of truth for both the batched path and each factor's
standalone `compute()`.

The other four (connectivity, daily essentials, pollution sources, noise sources) each
combine several sub-lookups with different curves, which a single proximity category
can't express, so they go through `service/osm_lookup.py` instead. That module is where
the bundled-vs-network decision lives, so all four inherit it, and it shares
`overpass_batch`'s mirror failover rather than hitting one hardcoded endpoint.

The network path is a fallback and should be treated as one. The public Overpass
cluster rate-limits under load and refuses cloud provider IPs outright, which is why
the bundle exists. A failed factor is floored, not hidden — see Scoring philosophy
below.

### What isn't built yet

[TODO.md](TODO.md) is the full list, tiered by how hard the data is to get rather than
how hard the code is. The short version: road quality, walkability and flood risk need
**no new access at all** (the tags are already in the OSM extract we download); real
ground-station air quality needs a **free API key** from OpenAQ or data.gov.in; price
per m² has a legal public source in Karnataka's guidance-value portal, unlike the
property portals whose terms forbid it; and crime, electricity and drinking water have
no source at the ~500m resolution this app scores at.

## Scoring philosophy

The system is biased against false positives: a factor that could not be verified
(upstream failure, or genuinely nothing found nearby) pulls the composite score
*down* toward a conservative floor rather than being excluded from the average.
See the backend's `service/aggregator.py` and `domain/models.py` for details.

## Running locally

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py   # or: uvicorn api.app:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # fill in VITE_GOOGLE_MAPS_API_KEY
npm run dev            # http://localhost:5173
```

Only one API key is required: a Google Maps JavaScript API key (with the Places API
enabled for address autocomplete). Every other data source used in v1 is free and
keyless.

## Deploying

The frontend is a static build; the backend is a long-running process, so they deploy
to different kinds of hosting.

### Backend → Render

`render.yaml` at the repo root is a Render Blueprint. In the Render dashboard: New →
Blueprint → point it at this repo. It builds `backend/` with
`pip install -r requirements.txt` and runs `uvicorn api.app:app --host 0.0.0.0 --port $PORT`.
It'll prompt you for one env var:

- `ALLOWED_ORIGINS` — your deployed frontend's URL (e.g. `https://qol-indicator.vercel.app`).
  Comma-separate multiple origins if needed. Defaults to `http://localhost:5173` only if unset.

Note the resulting backend URL (e.g. `https://qol-indicator-backend.onrender.com`) — the
frontend needs it next.

### Frontend → Vercel

`frontend/vercel.json` pins the build to Vite. In the Vercel dashboard: New Project →
import this repo → set **Root Directory** to `frontend` (this is a two-app repo, not a
single-app one, so Vercel needs to be told which subfolder to build). Add two
environment variables in the Vercel project settings:

- `VITE_GOOGLE_MAPS_API_KEY` — same key as local dev, but add the deployed frontend's
  domain to its HTTP-referrer restrictions in Google Cloud Console (Credentials → your key
  → Application restrictions).
- `VITE_API_BASE_URL` — the Render backend URL from the previous step.

### Before either will work

The code needs to be in a git repository connected to GitHub (or GitLab), since both
Render and Vercel deploy from a connected repo. That part — creating the repo, pushing,
and connecting the two dashboards — is a you-step; I can prep the code but can't create
accounts or push on your behalf.
