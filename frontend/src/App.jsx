import { useCallback, useState } from 'react'
import { fetchScore } from './api/scoreApi'
import MapView from './components/MapView'
import ScorePanel from './components/ScorePanel'

export default function App() {
  const [selectedLocation, setSelectedLocation] = useState(null)
  const [scoreData, setScoreData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleLocationSelect = useCallback(async (lat, lng) => {
    setSelectedLocation({ lat, lng })
    setLoading(true)
    setError(null)
    setScoreData(null)
    try {
      const data = await fetchScore(lat, lng)
      setScoreData(data)
    } catch {
      setError('Could not fetch a score for this location. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

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
          <ScorePanel loading={loading} error={error} data={scoreData} />
        </div>
      </div>
    </div>
  )
}
