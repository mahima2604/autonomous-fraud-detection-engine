import { useEffect, useMemo, useState } from 'react';
import { getCustomerDetails, getCustomers } from '../../services/adminCustomerService';
import RiskBadge from '../../components/fraud/RiskBadge';
import { formatCurrency, formatDate, formatDateTime } from '../../utils/formatters';
import './AdminCustomers.css';

const DECISION_CLASS = { APPROVE: 'badge-low', REVIEW: 'badge-medium', BLOCK: 'badge-high' };

function AdminCustomers() {
  const [customers, setCustomers] = useState([]);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [details, setDetails] = useState(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [listError, setListError] = useState(false);
  const [detailsError, setDetailsError] = useState(false);

  const loadCustomers = async () => {
    setListLoading(true);
    setListError(false);
    try {
      const data = await getCustomers();
      setCustomers(data);
    } catch {
      setListError(true);
    } finally {
      setListLoading(false);
    }
  };

  const loadDetails = async (customerId) => {
    setSelectedId(customerId);
    setDetails(null);
    setDetailsLoading(true);
    setDetailsError(false);
    try {
      setDetails(await getCustomerDetails(customerId));
    } catch {
      setDetailsError(true);
    } finally {
      setDetailsLoading(false);
    }
  };

  useEffect(() => { loadCustomers(); }, []);

  const filteredCustomers = useMemo(() => {
    const search = query.trim().toLowerCase();
    if (!search) return customers;
    return customers.filter((customer) =>
      (customer.name || '').toLowerCase().includes(search) || customer.email.toLowerCase().includes(search),
    );
  }, [customers, query]);

  return (
    <section className="admin-customers">
      <div className="admin-customers-heading">
        <div><p className="admin-eyebrow">Account management</p><h1>Customers</h1></div>
        <button className="btn btn-secondary" onClick={loadCustomers} disabled={listLoading}>Refresh</button>
      </div>

      <div className="card admin-customer-list">
        <div className="admin-customer-toolbar">
          <div><h2>Customer accounts</h2><p>Registered accounts from SecureCart.</p></div>
          <label className="admin-search">
            <span className="sr-only">Search customers by name or email</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or email" />
          </label>
        </div>
        {listLoading ? <p className="admin-state">Loading customers...</p> : listError ? (
          <div className="admin-state admin-state-error"><p>Unable to load customer data.</p><button className="btn btn-secondary btn-sm" onClick={loadCustomers}>Retry</button></div>
        ) : customers.length === 0 ? <p className="admin-state">No customers registered yet.</p> : filteredCustomers.length === 0 ? (
          <p className="admin-state">No customers match your search.</p>
        ) : (
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Name</th><th>Email</th><th>User ID</th><th>Status</th><th>Registered</th><th>Action</th></tr></thead>
            <tbody>{filteredCustomers.map((customer) => (
              <tr key={customer.id}>
                <td>{customer.name || '—'}</td><td>{customer.email}</td><td>{customer.id}</td>
                <td><span className={`badge ${customer.is_active ? 'badge-low' : 'badge-neutral'}`}>{customer.is_active ? 'Active' : 'Inactive'}</span></td>
                <td>{formatDate(customer.created_at)}</td>
                <td><button className="btn-link" onClick={() => loadDetails(customer.id)}>View Details</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {selectedId !== null && <section className="admin-customer-details" aria-live="polite">
        <div className="admin-details-heading"><h2>Customer details</h2><button className="btn-link" onClick={() => { setSelectedId(null); setDetails(null); }}>Close</button></div>
        {detailsLoading ? <p className="admin-state">Loading customer details...</p> : detailsError ? (
          <div className="admin-state admin-state-error"><p>Unable to load customer data.</p><button className="btn btn-secondary btn-sm" onClick={() => loadDetails(selectedId)}>Retry</button></div>
        ) : details && <>
          <div className="card card-padded admin-customer-profile">
            <div><span>Name</span><strong>{details.customer.name || '—'}</strong></div>
            <div><span>Email</span><strong>{details.customer.email}</strong></div>
            <div><span>User ID</span><strong>{details.customer.id}</strong></div>
            <div><span>Account status</span><strong>{details.customer.is_active ? 'Active' : 'Inactive'}</strong></div>
            <div><span>Registered</span><strong>{formatDate(details.customer.created_at)}</strong></div>
          </div>
          <div className="admin-transaction-heading"><h3>Customer transactions</h3></div>
          <div className="card table-scroll"><table className="data-table">
            <thead><tr><th>Transaction ID</th><th>Amount</th><th>Fraud Score</th><th>Risk</th><th>Decision</th><th>Model</th><th>Timestamp</th></tr></thead>
            <tbody>{details.transactions.length === 0 ? <tr><td colSpan="7" className="admin-table-empty">No transactions found for this customer.</td></tr> : details.transactions.map((transaction) => {
              const prediction = transaction.fraud_prediction;
              return <tr key={transaction.transaction_id}>
                <td>{transaction.transaction_id}</td><td>{formatCurrency(transaction.amount)}</td>
                {prediction ? <><td>{prediction.fraud_probability}</td><td><RiskBadge riskLevel={prediction.risk_level} /></td><td><span className={`badge ${DECISION_CLASS[prediction.decision] || 'badge-neutral'}`}>{prediction.decision}</span></td><td>{prediction.model_used || '—'}</td><td>{formatDateTime(prediction.created_at)}</td></> : <td colSpan="5" className="admin-prediction-missing">No fraud prediction available. <span className="admin-transaction-date">Transaction: {formatDateTime(transaction.created_at)}</span></td>}
              </tr>;
            })}</tbody>
          </table></div>
        </>}
      </section>}
    </section>
  );
}

export default AdminCustomers;
