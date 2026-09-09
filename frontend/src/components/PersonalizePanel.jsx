export default function PersonalizePanel({ age, onAgeChange }) {
  const handleChange = (event) => {
    const raw = event.target.value
    onAgeChange(raw === '' ? null : Number(raw))
  }

  return (
    <div className="personalize-panel">
      <label className="personalize-label" htmlFor="personalize-age">
        Personalize (optional)
      </label>
      <div className="personalize-row">
        <input
          id="personalize-age"
          type="number"
          min="0"
          max="120"
          placeholder="Age"
          value={age ?? ''}
          onChange={handleChange}
          className="personalize-age-input"
        />
        {age != null && (
          <button type="button" className="personalize-clear" onClick={() => onAgeChange(null)}>
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
