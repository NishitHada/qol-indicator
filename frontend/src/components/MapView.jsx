import { useCallback, useRef, useState } from 'react'
import { Autocomplete, GoogleMap, Marker, useJsApiLoader } from '@react-google-maps/api'

const LIBRARIES = ['places']
const DEFAULT_CENTER = { lat: 40.7829, lng: -73.9654 } // Central Park, NYC
const MAP_CONTAINER_STYLE = { width: '100%', height: '100%' }

export default function MapView({ onLocationSelect, selectedLocation }) {
  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY,
    libraries: LIBRARIES,
  })
  const [map, setMap] = useState(null)
  const autocompleteRef = useRef(null)

  const handleMapClick = useCallback(
    (event) => {
      onLocationSelect(event.latLng.lat(), event.latLng.lng())
    },
    [onLocationSelect],
  )

  const handlePlaceChanged = useCallback(() => {
    const place = autocompleteRef.current?.getPlace()
    const location = place?.geometry?.location
    if (!location) return
    const lat = location.lat()
    const lng = location.lng()
    onLocationSelect(lat, lng)
    map?.panTo({ lat, lng })
    map?.setZoom(15)
  }, [map, onLocationSelect])

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
      <div className="map-search-box">
        <Autocomplete onLoad={(ac) => (autocompleteRef.current = ac)} onPlaceChanged={handlePlaceChanged}>
          <input type="text" placeholder="Search an address..." className="map-search-input" />
        </Autocomplete>
      </div>
      <GoogleMap
        mapContainerStyle={MAP_CONTAINER_STYLE}
        center={DEFAULT_CENTER}
        zoom={13}
        onClick={handleMapClick}
        onLoad={setMap}
      >
        {selectedLocation && <Marker position={selectedLocation} />}
      </GoogleMap>
    </div>
  )
}
