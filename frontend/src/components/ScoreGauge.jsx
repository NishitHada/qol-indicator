function bandColor(score) {
  if (score < 40) return '#e05252'
  if (score < 70) return '#e0a752'
  return '#4caf7d'
}

export default function ScoreGauge({ score }) {
  const color = bandColor(score)
  return (
    <div className="score-gauge">
      <div className="score-gauge-number" style={{ color }}>
        {Math.round(score)}
      </div>
      <div className="score-gauge-bar-track">
        <div className="score-gauge-bar-fill" style={{ width: `${score}%`, backgroundColor: color }} />
      </div>
      <div className="score-gauge-label">Overall Quality of Life</div>
    </div>
  )
}
