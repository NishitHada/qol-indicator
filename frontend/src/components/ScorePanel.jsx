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

  const entries = Object.entries(data.factors ?? {})
  const mainEntries = entries.filter(([, factor]) => factor.status !== 'coming_soon')
  const stubEntries = entries.filter(([, factor]) => factor.status === 'coming_soon')
  // Defensive: the frontend and backend deploy independently (Vercel/Render), so a
  // field this build expects can briefly be absent from an older-deployed backend's
  // response. Falling back to [] means that version-skew window degrades gracefully
  // instead of crashing the whole app.
  const unverifiedFactors = data.unverified_factors ?? []
  const excludedFactors = data.excluded_factors ?? []
  const personalizationApplied = data.personalization_applied ?? []

  return (
    <div className="score-panel">
      <ScoreGauge score={data.overall_score} />
      {unverifiedFactors.length > 0 && (
        <div className="score-panel-note">
          {unverifiedFactors.length} factor(s) could not be verified for this location — the
          score above uses a conservative estimate for them rather than assuming they're fine.
        </div>
      )}
      {personalizationApplied.length > 0 && (
        <div className="score-panel-note score-panel-note-personalized">
          <span className="score-panel-note-title">Personalized for you</span>
          {/* A list rather than one joined string: several rules now fire at once for
              a filled-in profile, and running them together made an unreadable wall. */}
          <ul className="personalization-reasons">
            {personalizationApplied.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="factor-list">
        {mainEntries.map(([key, factor]) => (
          <FactorCard key={key} factor={factor} excluded={excludedFactors.includes(key)} />
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
