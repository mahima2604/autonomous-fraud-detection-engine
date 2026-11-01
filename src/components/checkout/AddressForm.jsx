import { useRef, useState } from 'react';
import AddressMap from './AddressMap';
import { reverseGeocode, searchAddresses } from '../../services/geocodingService';
import { getCurrentLocation } from '../../services/addressValidation';

function AddressForm({ values, onChange, prefix }) {
  const [point, setPoint] = useState(null);
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [locationError, setLocationError] = useState('');
  const [geocodedPostal, setGeocodedPostal] = useState('');
  const searchController = useRef(null);

  function handleChange(field) {
    return (e) => onChange({ ...values, [field]: e.target.value, addressConfirmed: false });
  }

  function applySuggestion(suggestion) {
    setPoint({ latitude: suggestion.latitude, longitude: suggestion.longitude });
    setGeocodedPostal(suggestion.address.postalCode);
    onChange({ ...values, ...suggestion.address, addressConfirmed: false });
    setSuggestions([]);
    setMessage('Review the suggested address and map marker, then confirm this delivery address below.');
    setLocationError('');
  }

  async function updateFromPoint(nextPoint) {
    setPoint(nextPoint);
    try {
      const suggestion = await reverseGeocode(nextPoint.latitude, nextPoint.longitude);
      if (suggestion) applySuggestion(suggestion);
      else setMessage('No address match was found. Edit the address fields or move the marker to the correct point.');
    } catch {
      setMessage('Could not retrieve an address for this point. Edit the fields manually.');
    }
  }

  function locateCustomer() {
    setLocationError('');
    getCurrentLocation(navigator.geolocation).then(updateFromPoint).catch((error) => setLocationError(error.message));
  }

  async function findAddress(event) {
    event?.preventDefault();
    if (query.trim().length < 3) return;
    searchController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    setBusy(true);
    setMessage('');
    await new Promise((resolve) => setTimeout(resolve, 500));
    try {
      const results = await searchAddresses(query.trim(), controller.signal);
      setSuggestions(results);
      setMessage(results.length ? '' : 'No matching address found. Edit the address or select the correct point on the map.');
    } catch (error) {
      if (error.name !== 'AbortError') setMessage(error.message || 'Address search failed. Enter the address manually.');
    } finally {
      if (searchController.current === controller) setBusy(false);
    }
  }

  return (
    <div>
      <div className="field">
        <label htmlFor={`${prefix}-fullName`}>Full name</label>
        <input id={`${prefix}-fullName`} value={values.fullName} onChange={handleChange('fullName')} required />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-locality`}>Locality / area</label>
        <input id={`${prefix}-locality`} value={values.locality || ''} onChange={handleChange('locality')} />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-line1`}>Address line</label>
        <input id={`${prefix}-line1`} value={values.line1} onChange={handleChange('line1')} required />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor={`${prefix}-city`}>City</label>
          <input id={`${prefix}-city`} value={values.city} onChange={handleChange('city')} required />
        </div>
        <div className="field">
          <label htmlFor={`${prefix}-postalCode`}>Postal code</label>
          <input id={`${prefix}-postalCode`} value={values.postalCode} onChange={handleChange('postalCode')} required />
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-state`}>State</label>
        <input id={`${prefix}-state`} value={values.state || ''} onChange={handleChange('state')} />
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-country`}>Country</label>
        <input id={`${prefix}-country`} value={values.country} onChange={handleChange('country')} required />
      </div>
      {prefix === 'ship' && <section aria-label="Find delivery address" className="address-picker">
        <h4>Find your delivery address</h4>
        <p>Search for a place or use your current location. Review all details before confirming.</p>
        <button type="button" className="btn btn-secondary" onClick={locateCustomer}>Use my current location</button>
        {locationError && <p role="alert" className="address-message address-error">{locationError}</p>}
        <div className="address-search">
          <label htmlFor={`${prefix}-search`}>Search for a place, street, or locality</label>
          <div className="address-search-row">
            <input id={`${prefix}-search`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. street or locality" />
            <button type="button" className="btn btn-secondary" onClick={findAddress} disabled={busy || query.trim().length < 3}>{busy ? 'Searching…' : 'Search'}</button>
          </div>
        </div>
        {suggestions.length > 0 && <ul className="address-suggestions" aria-label="Address suggestions">
          {suggestions.map((suggestion) => <li key={`${suggestion.latitude}:${suggestion.longitude}`}>
            <button type="button" onClick={() => applySuggestion(suggestion)}>{suggestion.label}</button>
          </li>)}
        </ul>}
        {point && <><AddressMap point={point} onMove={updateFromPoint} /><p className="address-hint">Click the map or drag the marker to refine the location.</p></>}
        {message && <p role="status" className="address-message">{message}</p>}
        {geocodedPostal && values.postalCode && geocodedPostal !== values.postalCode && <p role="alert" className="address-message address-warning">The selected map location has PIN code {geocodedPostal}, but the entered PIN is {values.postalCode}. Correct the address or confirm that these details are intentional.</p>}
        <label className="address-confirm"><input type="checkbox" checked={Boolean(values.addressConfirmed)} onChange={(event) => onChange({ ...values, addressConfirmed: event.target.checked })} /> I have reviewed and confirm this delivery address</label>
        <p className="address-attribution">Search by Photon. Map data &copy; OpenStreetMap contributors.</p>
      </section>}
    </div>
  );
}

export default AddressForm;
