export function validateAddress(address, { requireConfirmation = false } = {}) {
  const required = ['fullName', 'line1', 'city', 'postalCode', 'country'];
  if (required.some((key) => !String(address?.[key] || '').trim())) return 'Complete the required address fields.';
  if (!/^\d{6}$/.test(address.postalCode)) return 'Enter a valid six-digit Indian PIN code.';
  if (requireConfirmation && !address.addressConfirmed) return 'Review and explicitly confirm the delivery address.';
  return '';
}

const LOCATION_ERRORS = {
  1: 'Location permission was denied. You can still search for or enter the address manually.',
  2: 'Your location is unavailable. Try again or enter the address manually.',
  3: 'Location request timed out. Try again or enter the address manually.',
};

export function getCurrentLocation(geolocation) {
  if (!geolocation?.getCurrentPosition) {
    return Promise.reject(new Error('This browser does not support location. You can still search for or enter the address manually.'));
  }
  return new Promise((resolve, reject) => geolocation.getCurrentPosition(
    ({ coords }) => resolve({ latitude: coords.latitude, longitude: coords.longitude }),
    (error) => reject(new Error(LOCATION_ERRORS[error.code] || 'Could not get your location. Enter the address manually.')),
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
  ));
}
