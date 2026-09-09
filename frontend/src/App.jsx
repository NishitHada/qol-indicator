import { useCallback, useState } from 'react'
import { fetchScore } from './api/scoreApi'
import MapView from './components/MapView'
import PersonalizePanel from './components/PersonalizePanel'
import ScorePanel from './components/ScorePanel'

export default function App() {
  const [selectedLocation, setSelectedLocation] = useState(null)
  const [scoreData, setScoreData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [age, setAge] = useState(null)

  const runFetch = useCallback(async (lat, lng, currentAge) => {
    setLoading(true)
    setError(null)
    setScoreData(null)
    try {
      const data = await fetchScore(lat, lng, { age: currentAge })
      setScoreData(data)
    } catch {
      setError('Could not fetch a score for this location. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleLocationSelect = useCallback(
    (lat, lng) => {
      setSelectedLocation({ lat, lng })
      runFetch(lat, lng, age)
    },
    [age, runFetch],
  )

  const handleAgeChange = useCallback(
    (newAge) => {
      setAge(newAge)
      if (selectedLocation) {
        runFetch(selectedLocation.lat, selectedLocation.lng, newAge)
      }
    },
    [selectedLocation, runFetch],
  )

  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>Quality of Life Indicator</h1>
        <p>Click the map or search an address to see how a location scores.</p>
      </header>
      <div className="app-body">
        <div className="app-map-pane">
          <MapView onLocationSelect={handleLocationSelect} selectedLocation={selectedLocation} />
        </div>
        <div className="app-panel-pane">
          <PersonalizePanel age={age} onAgeChange={handleAgeChange} />
          <ScorePanel loading={loading} error={error} data={scoreData} />
        </div>
      </div>
    </div>
  )
}
