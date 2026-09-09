import { useCallback, useEffect, useRef, useState } from 'react'
import { GoogleMap, Marker, useJsApiLoader } from '@react-google-maps/api'

const LIBRARIES = ['places']
const DEFAULT_CENTER = { lat: 40.7829, lng: -73.9654 } // Central Park, NYC - fallback if geolocation is denied/unavailable
const MAP_CONTAINER_STYLE = { width: '100%', height: '100%' }

export default function MapView({ onLocationSelect, selectedLocation }) {
  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY,
    libraries: LIBRARIES,
  })
  const [center, setCenter] = useState(DEFAULT_CENTER)
  const [zoom, setZoom] = useState(13)
  const searchBoxRef = useRef(null)
  // The autocomplete element below is imperatively created once and never torn down,
  // so its handlers read onLocationSelect through this ref (always current) instead of
  // depending on the prop's identity directly - that identity changes on every
  // Personalize-panel keystroke (App.jsx recreates the callback per `age` change), and
  // this element must not be recreated or left listener-less each time that happens.
  const onLocationSelectRef = useRef(onLocationSelect)
  useEffect(() => {
    onLocationSelectRef.current = onLocationSelect
  }, [onLocationSelect])

  useEffect(() => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCenter({ lat: position.coords.latitude, lng: position.coords.longitude })
      },
      () => {
        // Permission denied or unavailable - keep the default fallback center.
      },
    )
  }, [])

  // google.maps.places.Autocomplete (the legacy widget @react-google-maps/api wraps) is
  // blocked entirely for API keys created after March 2025, so the search box is built
  // directly on the newer PlaceAutocompleteElement web component instead.
  useEffect(() => {
    if (!isLoaded || !searchBoxRef.current || searchBoxRef.current.childElementCount > 0) return

    const placeAutocomplete = new google.maps.places.PlaceAutocompleteElement()
    searchBoxRef.current.appendChild(placeAutocomplete)

    const lastSelectedAtRef = { current: 0 }

    const applyPlace = async (place) => {
      await place.fetchFields({ fields: ['location'] })
      const location = place.location
      if (!location) return
      const lat = location.lat()
      const lng = location.lng()
      onLocationSelectRef.current(lat, lng)
      setCenter({ lat, lng })
      setZoom(15)
    }

    const handleSelect = async ({ placePrediction }) => {
      lastSelectedAtRef.current = Date.now()
      await applyPlace(placePrediction.toPlace())
    }

    // gmp-select only fires when a suggestion is explicitly clicked, or arrow-key
    // highlighted then confirmed with Enter - pressing Enter right after typing, with
    // nothing highlighted, fires nothing at all. This fetches the top autocomplete
    // suggestion for whatever's typed as a fallback, so Enter always does something.
    // The timestamp comparison (rather than a boolean reset) avoids a race against
    // gmp-select firing as part of the same keydown when a suggestion *was* highlighted.
    const handleKeyDown = (event) => {
      if (event.key !== 'Enter') return
      const keydownAt = Date.now()
      window.setTimeout(async () => {
        if (lastSelectedAtRef.current >= keydownAt) return
        const query = placeAutocomplete.value
        if (!query) return
        try {
          const { suggestions } = await google.maps.places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
            input: query,
          })
          const top = suggestions?.[0]?.placePrediction
          if (!top) return
          await applyPlace(top.toPlace())
        } catch {
          // No match for the free-typed text - leave the map/score as-is.
        }
      }, 150)
    }

    placeAutocomplete.addEventListener('gmp-select', handleSelect)
    placeAutocomplete.addEventListener('keydown', handleKeyDown)
    return () => {
      placeAutocomplete.removeEventListener('gmp-select', handleSelect)
      placeAutocomplete.removeEventListener('keydown', handleKeyDown)
    }
    // Deliberately just [isLoaded]: this creates the element exactly once. See the
    // onLocationSelectRef comment above for why onLocationSelect isn't a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded])

  const handleMapClick = useCallback(
    (event) => {
      onLocationSelect(event.latLng.lat(), event.latLng.lng())
    },
    [onLocationSelect],
  )

  if (loadError) {
    return (
      <div className="map-status map-status-error">
        Failed to load Google Maps. Check that VITE_GOOGLE_MAPS_API_KEY is set correctly.
      </div>
    )
  }
  if (!isLoaded) {
    return <div className="map-status">Loading map...</div>
  }

  return (
    <div className="map-view">
      <div className="map-search-box" ref={searchBoxRef} />
      <GoogleMap mapContainerStyle={MAP_CONTAINER_STYLE} center={center} zoom={zoom} onClick={handleMapClick}>
        {selectedLocation && <Marker position={selectedLocation} />}
      </GoogleMap>
    </div>
  )
}
