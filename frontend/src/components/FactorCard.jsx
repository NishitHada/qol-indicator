function bandColor(score) {
  if (score < 40) return '#e05252'
  if (score < 70) return '#e0a752'
  return '#4caf7d'
}

export default function FactorCard({ factor, excluded = false }) {
  const { label, score, raw_value: rawValue, unit, status, detail } = factor

  // Deliberately checked before status. An excluded factor may well have resolved
  // fine; it is not counted because the user said it does not apply to them, and
  // showing it as a score would imply it fed into the total.
  if (excluded) {
    return (
      <div className="factor-card factor-card-stub">
        <span className="factor-card-label">{label}</span>
        <span className="factor-card-badge">Not counted for you</span>
      </div>
    )
  }

  if (status === 'coming_soon') {
    return (
      <div className="factor-card factor-card-stub">
        <span className="factor-card-label">{label}</span>
        <span className="factor-card-badge">Coming soon</span>
      </div>
    )
  }

  if (status === 'not_found' || status === 'error') {
    return (
      <div className="factor-card factor-card-neutral">
        <span className="factor-card-label">{label}</span>
        <span className="factor-card-badge factor-card-badge-neutral">
          {status === 'not_found' ? 'Not found nearby' : "Couldn't verify"}
        </span>
      </div>
    )
  }

  const color = bandColor(score)
  return (
    <div className="factor-card">
      <div className="factor-card-header">
        <span className="factor-card-label">{label}</span>
        <span className="factor-card-score" style={{ color }}>
          {Math.round(score)}
        </span>
      </div>
      <div className="factor-card-bar-track">
        <div className="factor-card-bar-fill" style={{ width: `${score}%`, backgroundColor: color }} />
      </div>
      {(rawValue != null || detail) && (
        <div className="factor-card-detail">
          {rawValue != null && unit ? `${rawValue} ${unit}` : null}
          {detail ? ` · ${detail}` : null}
        </div>
      )}
    </div>
  )
}
