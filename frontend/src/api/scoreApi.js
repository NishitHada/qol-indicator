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
