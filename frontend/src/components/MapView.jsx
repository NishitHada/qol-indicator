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

    const handleSelect = async ({ placePrediction }) => {
      const place = placePrediction.toPlace()
      await place.fetchFields({ fields: ['location'] })
      const location = place.location
      if (!location) return
      const lat = location.lat()
      const lng = location.lng()
      onLocationSelect(lat, lng)
      setCenter({ lat, lng })
      setZoom(15)
    }

    placeAutocomplete.addEventListener('gmp-select', handleSelect)
    return () => placeAutocomplete.removeEventListener('gmp-select', handleSelect)
  }, [isLoaded, onLocationSelect])

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
