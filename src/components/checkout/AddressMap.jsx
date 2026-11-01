import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

function AddressMap({ point, onMove }) {
  const element = useRef(null);
  const map = useRef(null);
  const marker = useRef(null);
  const onMoveRef = useRef(onMove);
  onMoveRef.current = onMove;

  useEffect(() => {
    if (!element.current || map.current) return undefined;
    map.current = L.map(element.current).setView([20.5937, 78.9629], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map.current);
    map.current.on('click', (event) => onMoveRef.current({ latitude: event.latlng.lat, longitude: event.latlng.lng }));
    return () => { map.current?.remove(); map.current = null; marker.current = null; };
  }, []);

  useEffect(() => {
    if (!point || !map.current) return;
    const position = [point.latitude, point.longitude];
    map.current.setView(position, 16);
    if (!marker.current) marker.current = L.marker(position, { draggable: true }).addTo(map.current)
      .on('dragend', (event) => {
        const next = event.target.getLatLng();
        onMoveRef.current({ latitude: next.lat, longitude: next.lng });
      });
    else marker.current.setLatLng(position);
  }, [point]);

  return <div className="checkout-map" ref={element} role="application" aria-label="Delivery address map" />;
}

export default AddressMap;
