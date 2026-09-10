import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchComparison, fetchScore, resolveShareCode } from './api/scoreApi'
import ComparePanel from './components/ComparePanel'
import MapView from './components/MapView'
import PersonalizePanel from './components/PersonalizePanel'
import ScorePanel from './components/ScorePanel'
import ShareButton from './components/ShareButton'

const SLOT_NAMES = ['A', 'B']

function shareCodeFromUrl() {
  const match = window.location.hash.match(/^#s=(.+)$/)
  return match ? match[1] : null
}

export default function App() {
  // One array for both modes: index 0 is the location in single mode and A in
  // compare mode. Keeping a single source of truth means switching modes never has
  // to copy a location from one piece of state to another.
  const [locations, setLocations] = useState([])
  const [compareMode, setCompareMode] = useState(false)
  const [activeSlot, setActiveSlot] = useState(0)
  const [focus, setFocus] = useState(null)
  const [scoreData, setScoreData] = useState(null)
  const [compareData, setCompareData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [profile, setProfile] = useState({ age: null, religion: null, transportPreference: null })

  const run = useCallback(async (points, currentProfile, comparing) => {
    if (points.length === 0 || (comparing && points.length < 2)) return
    setLoading(true)
    setError(null)
    try {
      if (comparing) {
        setCompareData(await fetchComparison(points, currentProfile))
      } else {
        setScoreData(await fetchScore(points[0].lat, points[0].lng, currentProfile))
      }
    } catch {
      setError('Could not fetch a score for this location. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleLocationSelect = useCallback(
    (lat, lng) => {
      const point = { lat, lng }
      // Deliberately derived from `locations` rather than from a setLocations updater.
      // An updater must be pure - StrictMode calls it twice - and this needs to fire a
      // request and move the active slot, neither of which may happen twice.
      if (!compareMode) {
        setLocations([point])
        setScoreData(null)
        run([point], profile, false)
        return
      }

      const next = [...locations]
      next[activeSlot] = point
      setLocations(next)
      setCompareData(null)
      // Filling A moves the next click to B, which is what someone picking two places
      // to compare almost always wants next.
      if (activeSlot === 0 && next[1] == null) {
        setActiveSlot(1)
      }
      if (next[0] && next[1]) {
        run(next, profile, true)
      }
    },
    [profile, activeSlot, compareMode, locations, run],
  )

  const handleProfileChange = useCallback(
    (next) => {
      setProfile(next)
      run(locations.filter(Boolean), next, compareMode)
    },
    [locations, compareMode, run],
  )

  const startCompare = useCallback(() => {
    setCompareMode(true)
    setActiveSlot(1)
    setCompareData(null)
  }, [])

  const exitCompare = useCallback(() => {
    setCompareMode(false)
    setActiveSlot(0)
    setCompareData(null)
    setLocations((current) => current.slice(0, 1))
    if (locations[0]) run([locations[0]], profile, false)
  }, [locations, profile, run])

  // A shared link restores the whole view: both pins, the profile, and which panel to
  // show. Runs once - after that the hash is just history, and re-reading it would
  // fight with whatever the user has done since.
  const restoredRef = useRef(false)
  useEffect(() => {
    if (restoredRef.current) return
    restoredRef.current = true
    const code = shareCodeFromUrl()
    if (!code) return
    ;(async () => {
      try {
        const payload = await resolveShareCode(code)
        const points = payload.locations.map(({ lat, lng }) => ({ lat, lng }))
        const sharedProfile = {
          age: payload.profile?.age ?? null,
          religion: payload.profile?.religion ?? null,
          transportPreference: payload.profile?.transport_preference ?? null,
        }
        const comparing = points.length > 1
        setLocations(points)
        setProfile(sharedProfile)
        setCompareMode(comparing)
        setActiveSlot(comparing ? 1 : 0)
        setFocus(points)
        run(points, sharedProfile, comparing)
      } catch {
        setError('That share link could not be opened.')
      }
    })()
  }, [run])

  const hasSomethingToShare = locations.length > 0 && locations[0] != null
  const prompt = compareMode
    ? `Click the map or search to set location ${SLOT_NAMES[activeSlot]}.`
    : 'Click the map or search an address to see how a location scores.'

  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>Quality of Life Indicator</h1>
        <p>{prompt}</p>
      </header>
      <div className="app-body">
        <div className="app-map-pane">
          <MapView
            onLocationSelect={handleLocationSelect}
            markers={locations}
            markerLabels={compareMode ? SLOT_NAMES : null}
            focusLocations={focus}
          />
        </div>
        <div className="app-panel-pane">
          <PersonalizePanel profile={profile} onChange={handleProfileChange} />

          {compareMode && (
            <div className="compare-controls">
              {SLOT_NAMES.map((name, index) => (
                <button
                  key={name}
                  type="button"
                  className={index === activeSlot ? 'slot-chip slot-chip-active' : 'slot-chip'}
                  onClick={() => setActiveSlot(index)}
                >
                  <span className="compare-pin" data-slot={name}>
                    {name}
                  </span>
                  {locations[index]
                    ? `${locations[index].lat.toFixed(4)}, ${locations[index].lng.toFixed(4)}`
                    : 'Not set'}
                </button>
              ))}
              <button type="button" className="compare-exit" onClick={exitCompare}>
                Exit compare
              </button>
            </div>
          )}

          {compareMode ? (
            <ComparePanel loading={loading} error={error} data={compareData} locations={locations} />
          ) : (
            <>
              <ScorePanel loading={loading} error={error} data={scoreData} />
              {scoreData && (
                <button type="button" className="compare-start" onClick={startCompare}>
                  Compare with another location
                </button>
              )}
            </>
          )}

          {hasSomethingToShare && (
            <ShareButton
              locations={locations.filter(Boolean)}
              profile={profile}
              disabled={compareMode && locations.filter(Boolean).length < 2}
            />
          )}
        </div>
      </div>
    </div>
  )
}
