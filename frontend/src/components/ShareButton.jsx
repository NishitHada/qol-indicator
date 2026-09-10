import { useCallback, useState } from 'react'
import { createShareCode } from '../api/scoreApi'

export function buildShareUrl(code) {
  const { origin, pathname } = window.location
  return `${origin}${pathname}#s=${code}`
}

export default function ShareButton({ locations, profile, disabled }) {
  const [state, setState] = useState('idle')
  const [url, setUrl] = useState(null)

  const handleShare = useCallback(async () => {
    setState('working')
    try {
      const code = await createShareCode(locations, profile)
      const shareUrl = buildShareUrl(code)
      setUrl(shareUrl)
      try {
        await navigator.clipboard.writeText(shareUrl)
        setState('copied')
      } catch {
        // Clipboard access needs a secure context and a user gesture, and is refused
        // outright in some browsers. The link is still shown below so it can be
        // copied by hand rather than the whole action failing.
        setState('ready')
      }
    } catch {
      setState('error')
    }
  }, [locations, profile])

  return (
    <div className="share-box">
      <button type="button" className="share-button" onClick={handleShare} disabled={disabled || state === 'working'}>
        {state === 'working' ? 'Creating link...' : state === 'copied' ? 'Link copied' : 'Share this view'}
      </button>
      {state === 'error' && <span className="share-hint share-hint-error">Could not create a link.</span>}
      {url && state !== 'error' && (
        <input className="share-url" readOnly value={url} onFocus={(event) => event.target.select()} />
      )}
    </div>
  )
}
