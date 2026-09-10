import ScoreGauge from './ScoreGauge'

const SLOT_NAMES = ['A', 'B', 'C', 'D']

function Verdict({ winner, difference, slotCount }) {
  if (winner == null) {
    // Deliberately two different messages. "Too close to call" means both sides
    // answered and landed within the tie threshold; "not comparable" means at least
    // one side could not be scored, which is a different thing and must not read as
    // a draw.
    const text = difference == null ? 'Not comparable' : 'Too close to call'
    return <span className="compare-verdict compare-verdict-tie">{text}</span>
  }
  return (
    <span className="compare-verdict" data-slot={SLOT_NAMES[winner]}>
      {slotCount > 2 ? SLOT_NAMES[winner] : `${SLOT_NAMES[winner]} wins`} +{difference}
    </span>
  )
}

function ScoreCell({ score, isWinner }) {
  if (score == null) {
    return <span className="compare-cell compare-cell-missing">—</span>
  }
  return (
    <span className={isWinner ? 'compare-cell compare-cell-winner' : 'compare-cell'}>
      {Math.round(score)}
    </span>
  )
}

export default function ComparePanel({ loading, error, data, locations }) {
  if (loading) {
    return <div className="score-panel score-panel-empty">Comparing locations...</div>
  }
  if (error) {
    return <div className="score-panel score-panel-empty score-panel-error">{error}</div>
  }
  if (!data) {
    return (
      <div className="score-panel score-panel-empty">
        Pick a second location on the map to compare it against the first.
      </div>
    )
  }

  const scored = data.locations ?? []
  const factors = Object.entries(data.factors ?? {})
  const overallWinner = data.overall_winner

  return (
    <div className="score-panel">
      <div className="compare-headline">
        {scored.map((entry, index) => (
          <div
            key={index}
            className={index === overallWinner ? 'compare-column compare-column-winner' : 'compare-column'}
          >
            <div className="compare-column-title">
              <span className="compare-pin" data-slot={SLOT_NAMES[index]}>
                {SLOT_NAMES[index]}
              </span>
              {locations?.[index]?.label ?? `${entry.location.lat.toFixed(4)}, ${entry.location.lng.toFixed(4)}`}
            </div>
            <ScoreGauge score={entry.overall_score} />
          </div>
        ))}
      </div>

      <div className="score-panel-note">
        {overallWinner == null
          ? `Overall these two are within ${data.overall_difference} points — too close to call.`
          : `${SLOT_NAMES[overallWinner]} scores ${data.overall_difference} points higher overall.`}
      </div>

      <div className="compare-table">
        {factors.map(([key, factor]) => (
          <div className="compare-row" key={key}>
            <span className="compare-row-label">{factor.label}</span>
            <span className="compare-row-scores">
              {factor.scores.map((score, index) => (
                <ScoreCell key={index} score={score} isWinner={index === factor.winner} />
              ))}
            </span>
            <Verdict winner={factor.winner} difference={factor.difference} slotCount={scored.length} />
          </div>
        ))}
      </div>
    </div>
  )
}
