const PHOTON_URL = 'https://photon.komoot.io';

async function request(url, signal) {
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('The address search service is temporarily unavailable.');
  return response.json();
}

function toSuggestion(feature) {
  const p = feature.properties || {};
  const street = [p.housenumber, p.street || p.name].filter(Boolean).join(' ');
  const locality = p.suburb || p.district || p.locality || '';
  return {
    label: [street, locality, p.city || p.town || p.village, p.state, p.postcode, p.country].filter(Boolean).join(', '),
    latitude: feature.geometry.coordinates[1], longitude: feature.geometry.coordinates[0],
    address: { line1: street || locality || p.name || '', locality, city: p.city || p.town || p.village || '', state: p.state || '', postalCode: p.postcode || '', country: p.country || '' },
  };
}

export async function searchAddresses(query, signal) {
  const url = new URL(`${PHOTON_URL}/api/`);
  url.searchParams.set('q', query);
  url.searchParams.set('limit', '5');
  url.searchParams.set('lang', 'en');
  return (await request(url, signal)).features.map(toSuggestion).filter((item) => item.label);
}

export async function reverseGeocode(latitude, longitude, signal) {
  const url = new URL(`${PHOTON_URL}/reverse`);
  url.searchParams.set('lat', latitude);
  url.searchParams.set('lon', longitude);
  const result = await request(url, signal);
  return result.features?.[0] ? toSuggestion(result.features[0]) : null;
}
