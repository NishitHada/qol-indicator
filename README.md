# Quality of Life Indicator

Drop a pin (or search an address) on a Google Map and get a composite "quality of life"
score plus a factor-by-factor breakdown for that location.

## v1 factors (live)

- Greenery proximity (OpenStreetMap Overpass)
- Water proximity (OpenStreetMap Overpass)
- Air quality / AQI (Open-Meteo)
- Temperature: average & extremes (Open-Meteo)

Everything else (pollution/noise sources, wind ventilation, crime rate, locality
premium-ness, road quality, drinking water, electricity availability, bad odour,
price per m²) is registered as a stub factor (`status: "coming_soon"`) so it can be
implemented later without touching the aggregator or frontend rendering logic.

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
