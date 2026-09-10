const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// `profile` is entirely optional - pass `{ age }` to personalize, or omit/null for
// the default (unpersonalized) score. Only non-null fields are sent, so a partially
// filled-out profile doesn't accidentally send `age: null` and confuse the backend.
export async function fetchScore(lat, lng, profile = null) {
  const body = { lat, lng }
  if (profile && profile.age != null) {
    body.profile = { age: profile.age }
  }

  const res = await fetch(`${API_BASE}/api/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`Score request failed: ${res.status}`)
  }
  return res.json()
}

// Two to four locations scored against each other under one profile, plus a
// factor-by-factor verdict. The backend does the comparing rather than the frontend so
// that the same answer is available to anything else built on the API later.
export async function fetchComparison(locations, profile = null) {
  const body = { locations: locations.map(({ lat, lng }) => ({ lat, lng })) }
  if (profile && profile.age != null) {
    body.profile = { age: profile.age }
  }
  const res = await fetch(`${API_BASE}/api/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`Compare request failed: ${res.status}`)
  }
  return res.json()
}

// Share codes carry their whole payload, so they are stable for a given view and
// never expire. Encoding lives on the backend to keep one implementation of the
// format rather than two that can drift apart.
export async function createShareCode(locations, profile = null) {
  const body = { locations: locations.map(({ lat, lng }) => ({ lat, lng })) }
  if (profile && profile.age != null) {
    body.profile = { age: profile.age }
  }
  const res = await fetch(`${API_BASE}/api/share`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`Share request failed: ${res.status}`)
  }
  return (await res.json()).code
}

export async function resolveShareCode(code) {
  const res = await fetch(`${API_BASE}/api/share/${encodeURIComponent(code)}`)
  if (!res.ok) {
    throw new Error(`Share code could not be resolved: ${res.status}`)
  }
  return res.json()
}
