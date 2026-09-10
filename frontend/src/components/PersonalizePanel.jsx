// Values match the backend's enums exactly, which in turn match OpenStreetMap's own
// religion tag values - so there is no translation table anywhere in the stack.
const RELIGIONS = [
  ['hindu', 'Hindu'],
  ['muslim', 'Muslim'],
  ['christian', 'Christian'],
  ['jain', 'Jain'],
  ['sikh', 'Sikh'],
  ['buddhist', 'Buddhist'],
  ['jewish', 'Jewish'],
]

const TRANSPORT = [
  ['metro', 'Metro'],
  ['bus', 'Bus'],
  ['cab', 'Cab / own vehicle'],
]

export default function PersonalizePanel({ profile, onChange }) {
  const { age = null, religion = null, transportPreference = null } = profile ?? {}
  const set = (field) => (event) => {
    const raw = event.target.value
    onChange({ ...profile, [field]: raw === '' ? null : raw })
  }
  const isSet = age != null || religion != null || transportPreference != null

  return (
    <div className="personalize-panel">
      <div className="personalize-header">
        <label className="personalize-label" htmlFor="personalize-age">
          Personalize (optional)
        </label>
        {isSet && (
          <button
            type="button"
            className="personalize-clear"
            onClick={() => onChange({ age: null, religion: null, transportPreference: null })}
          >
            Clear all
          </button>
        )}
      </div>

      <div className="personalize-row">
        <input
          id="personalize-age"
          type="number"
          min="0"
          max="120"
          placeholder="Age"
          value={age ?? ''}
          onChange={(event) => onChange({ ...profile, age: event.target.value === '' ? null : Number(event.target.value) })}
          className="personalize-age-input"
        />

        <select
          className="personalize-select"
          aria-label="Religion"
          value={religion ?? ''}
          onChange={set('religion')}
        >
          <option value="">Any faith</option>
          {RELIGIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>

        <select
          className="personalize-select"
          aria-label="Usual transport"
          value={transportPreference ?? ''}
          onChange={set('transportPreference')}
        >
          <option value="">Any transport</option>
          {TRANSPORT.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {religion && (
        <p className="personalize-hint">
          Religious site proximity now looks only for {RELIGIONS.find(([v]) => v === religion)[1]} places of
          worship, so it can score lower than it would otherwise.
        </p>
      )}
      {transportPreference === 'cab' && (
        <p className="personalize-hint">Public transport connectivity is not counted for cab users.</p>
      )}
      {(transportPreference === 'metro' || transportPreference === 'bus') && (
        <p className="personalize-hint">
          Connectivity now counts only {transportPreference} stops, ignoring the other modes.
        </p>
      )}
    </div>
  )
}
