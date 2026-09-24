// AddressForm.jsx — reusable shipping/billing address field group.
function AddressForm({ values, onChange, prefix }) {
  function handleChange(field) {
    return (e) => onChange({ ...values, [field]: e.target.value });
  }

  return (
    <div>
      <div className="field">
        <label htmlFor={`${prefix}-fullName`}>Full name</label>
        <input id={`${prefix}-fullName`} value={values.fullName} onChange={handleChange('fullName')} required />
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
        <label htmlFor={`${prefix}-country`}>Country</label>
        <input id={`${prefix}-country`} value={values.country} onChange={handleChange('country')} required />
      </div>
    </div>
  );
}

export default AddressForm;
