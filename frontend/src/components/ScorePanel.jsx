import FactorCard from './FactorCard'
import ScoreGauge from './ScoreGauge'

export default function ScorePanel({ loading, error, data }) {
  if (loading) {
    return <div className="score-panel score-panel-empty">Loading score...</div>
  }
  if (error) {
    return <div className="score-panel score-panel-empty score-panel-error">{error}</div>
  }
  if (!data) {
    return (
      <div className="score-panel score-panel-empty">
        Click the map or search an address to see its Quality of Life score.
      </div>
    )
  }

  const entries = Object.entries(data.factors)
  const mainEntries = entries.filter(([, factor]) => factor.status !== 'coming_soon')
  const stubEntries = entries.filter(([, factor]) => factor.status === 'coming_soon')

  return (
    <div className="score-panel">
      <ScoreGauge score={data.overall_score} />
      {data.unverified_factors.length > 0 && (
        <div className="score-panel-note">
          {data.unverified_factors.length} factor(s) could not be verified for this location — the
          score above uses a conservative estimate for them rather than assuming they're fine.
        </div>
      )}
      <div className="factor-list">
        {mainEntries.map(([key, factor]) => (
          <FactorCard key={key} factor={factor} />
        ))}
      </div>
      {stubEntries.length > 0 && (
        <>
          <div className="factor-list-heading">Coming in a future version</div>
          <div className="factor-list factor-list-stub">
            {stubEntries.map(([key, factor]) => (
              <FactorCard key={key} factor={factor} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
