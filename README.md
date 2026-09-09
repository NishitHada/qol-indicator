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
        │     ├─ noise_sources   local_osm (roads/airports) + adsb.lol (live flights)
        │     ├─ temperature     local_climate (bundled) → Open-Meteo archive
        │     └─ aqi             Open-Meteo air-quality (365-day window)
        └─ compute_overall() → weights (× personalization) → composite score
```

**Data sources, and why each lives where it does:**

| Factor | Source | Bundled? |
|---|---|---|
| Greenery, water, healthcare, social hub, religious site | OpenStreetMap | ✅ `data/bangalore_osm.json.gz` |
| Noise sources | OSM roads/airports + adsb.lol live flights | ✅ (OSM part) / live (flights) |
| Temperature | Open-Meteo archive (ERA5) | ✅ `data/bangalore_climate.json.gz` |
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

## v1 factors (live)

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

Everything else (pollution sources, wind ventilation, crime rate, locality
premium-ness, road quality, drinking water, electricity availability, bad odour,
price per m²) is registered as a stub factor (`status: "coming_soon"`) so it can be
implemented later without touching the aggregator or frontend rendering logic.

### Personalization (optional)

`POST /api/score` accepts an optional `profile: { age }`. With no profile (or an
empty one), the score is computed with the registry's base weights, unchanged -
personalization is opt-in, never mandatory. With a profile, `service/personalization.py`
applies matching rules (e.g. age ≤ 30 boosts `social_hub_proximity`; age 60+ boosts
`healthcare_proximity`, `religious_site_proximity`, and `aqi`) as weight multipliers,
then renormalizes every enabled factor's weight back to sum to 1.0 - so personalization
only ever shifts relative emphasis between factors, never the 0-100 range of the
result or the floor-on-failure behavior. The response's `personalization_applied`
lists which rules actually fired, and the frontend surfaces that as a note under the
score. The rule table is declarative and additive, the same spirit as
`FACTOR_REGISTRY` - a new personalization dimension (e.g. `has_children`) means
adding rules, not restructuring the aggregator.

### Bundled data (the important one)

Two datasets ship with the app and cover the same Bangalore bounding box
(12.70–13.25 N, 77.30–77.90 E). Inside it, six of the eight factors need **no network
call at all**:

| File | Size | Contents | Serves |
|---|---|---|---|
| `backend/data/bangalore_osm.json.gz` | 0.4 MB | 30,853 OSM features | greenery, water, healthcare, social hub, religious site, roads/airports |
| `backend/data/bangalore_climate.json.gz` | 0.05 MB | 42-point grid × 366 daily max/min/mean | temperature |

These exist because **both upstreams block or throttle cloud provider IPs.** Verified
from Render's outbound IP: every Overpass mirror returns connection-refused, and
Open-Meteo's archive returns `429` — while both serve the identical requests fine from
an ordinary machine. That is why production resolved only AQI and temperature at
first, then only 7/8. No amount of mirror failover, batching or cache tuning fixes an
endpoint that won't accept your IP.

It's also simply the right design. Parks and lakes don't move, and last year's weather
is settled history — neither belonged behind a per-request API call. Measured on a
real Bangalore point: **8/8 factors in ~0.2–0.8s**, versus 2/8 in 30–55s before.

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
```

Points outside the bundled bounds fall back to the network paths described below. To
cover another city, widen the bbox in both scripts and re-run them.

### Overpass batching (the network fallback path)

5 of the 6 Overpass-dependent factors (greenery, water, healthcare, social hub,
religious site - everything except `noise_sources`, which has its own separate live-
flight component) are resolved through `service/overpass_batch.py`, which combines
them into as few HTTP calls as possible instead of each firing its own request: one
combined query covers every category not already cached, and a second (only if
needed) retries whichever categories came back empty at their fallback radius. This
replaced 5 separate concurrent requests per score with 1-2, which was the single
biggest source of the "N factors couldn't be verified" rate-limiting this app used to
hit in practice. `service/overpass_categories.py` is the shared definition of each
category's tags/radius/scoring curve - the single source of truth both the batched
aggregator path and each factor's standalone `compute()` read from.

Even batched, this all depends on one shared free public `overpass-api.de` instance,
which does rate-limit under heavy use (we hit real `429`s while testing this very
session, from this session's own cumulative request volume). Handled gracefully - a
failed factor is floored, not hidden, see Scoring philosophy below - but a second
Overpass mirror as a fallback vendor (the existing multi-vendor pattern in
`service/vendor_fallback.py` already supports this) is worth adding if this keeps
being the bottleneck.

### Candidate data sources not yet wired in (todo)

Found while surveying [bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)
for ideas. Deferred because each has weak or nonexistent coverage for Bangalore/India
specifically, not because the source itself is bad:

- **USGS earthquake feed** (keyless, global) — Karnataka is India's lowest seismic
  hazard zone (Zone II), so this would rarely have meaningful signal for Bangalore.
  Worth revisiting if the app ever targets other regions.
- **NASA FIRMS active fires** (needs a free key, global) — Bangalore's urban core
  doesn't have the recurring fire signal that e.g. Delhi gets from stubble burning.
- **TomTom live traffic flow** — an optional enhanced vendor for `noise_sources`
  (Bangalore is a genuinely high-traffic-noise city) on top of the current
  OSM-only baseline, once a free TomTom key is added.
- **GBFS bikeshare feeds** (transit/mobility-access factor) — checked the official
  system registry directly: **zero GBFS systems currently exist in India**, not just
  Bangalore. Blocked until an Indian city publishes one, not just deprioritized.

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
