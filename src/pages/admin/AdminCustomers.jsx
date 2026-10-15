// AdminCustomers.jsx
// Enterprise Customer Directory & Individual Fraud Profile View.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCustomers } from '../../services/adminCustomerService';
import { formatDate } from '../../utils/formatters';
import './AdminCustomers.css';

function AdminCustomers() {
  const navigate = useNavigate();
  const [customers, setCustomers] = useState([]);
  const [query, setQuery] = useState('');
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(false);

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

  useEffect(() => {
    loadCustomers();
  }, []);

  const filteredCustomers = useMemo(() => {
    const search = query.trim().toLowerCase();
    if (!search) return customers;
    return customers.filter(
      (customer) =>
        (customer.name || '').toLowerCase().includes(search) ||
        customer.email.toLowerCase().includes(search) ||
        String(customer.id).includes(search),
    );
  }, [customers, query]);

  return (
    <section className="admin-customers">
      {/* Page Header */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <span className="admin-kicker-dot" />
            <span>Customer Directory</span>
          </div>
          <h1 className="admin-page-title">Customer Accounts & Risk Profiles</h1>
          <p className="admin-page-subtitle">
            Registered customer accounts, activity histories, and correlated fraud scoring assessments.
          </p>
        </div>
        <div className="admin-header-actions">
          <button
            id="admin-customers-refresh-btn"
            className="btn btn-secondary admin-refresh-btn"
            onClick={loadCustomers}
            disabled={listLoading}
            title="Refresh customer accounts"
          >
            <svg
              className={`admin-refresh-icon ${listLoading ? 'spinning' : ''}`}
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
            </svg>
            <span>{listLoading ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Main Customers List Card */}
      <div className="card admin-table-card">
        <div className="admin-table-toolbar">
          <div className="admin-toolbar-title-wrap">
            <h2 className="admin-card-title">Registered Accounts</h2>
            <p className="admin-card-description">
              Showing {filteredCustomers.length} of {customers.length} verified customer accounts.
            </p>
          </div>
          <div className="admin-toolbar-controls">
            <div className="admin-search-wrapper">
              <svg className="admin-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                id="admin-customers-search"
                type="text"
                className="admin-input admin-search-input"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by name, email, or user ID..."
              />
              {query && (
                <button
                  type="button"
                  className="admin-search-clear"
                  onClick={() => setQuery('')}
                  title="Clear search"
                >
                  &times;
                </button>
              )}
            </div>
          </div>
        </div>

        {listLoading ? (
          <div className="admin-table-state">
            <div className="spinner spinner-dark" />
            <p>Loading registered customers...</p>
          </div>
        ) : listError ? (
          <div className="admin-table-state admin-table-error">
            <p>Unable to retrieve customer directory.</p>
            <button className="btn btn-secondary btn-sm" onClick={loadCustomers}>
              Retry
            </button>
          </div>
        ) : customers.length === 0 ? (
          <div className="admin-table-state">
            <p>No customers registered yet in the system.</p>
          </div>
        ) : filteredCustomers.length === 0 ? (
          <div className="admin-table-state">
            <p>No customer accounts match your search query "{query}".</p>
          </div>
        ) : (
          <div className="admin-table-scroll-container">
            <table className="admin-table admin-customers-table">
              <thead>
                <tr>
                  <th className="th-cust-name">Customer Name</th>
                  <th className="th-cust-email">Email Address</th>
                  <th className="th-cust-id">User ID</th>
                  <th className="th-cust-status">Account Status</th>
                  <th className="th-cust-date">Registration Date</th>
                  <th className="th-cust-action">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredCustomers.map((customer) => {
                  return (
                    <tr key={customer.id}>
                      <td className="td-cust-name">
                        <div className="customer-avatar-row">
                          <span className="customer-avatar-circle">
                            {(customer.name || customer.email || 'U').charAt(0).toUpperCase()}
                          </span>
                          <strong className="customer-name-text">{customer.name || 'Name unavailable'}</strong>
                        </div>
                      </td>
                      <td className="td-cust-email">
                        <span className="customer-email-text">{customer.email}</span>
                      </td>
                      <td className="td-cust-id">
                        <span className="admin-user-id-badge">USR-#{customer.id}</span>
                      </td>
                      <td className="td-cust-status">
                        <span className={`badge ${customer.is_active ? 'badge-low' : 'badge-neutral'}`}>
                          {customer.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="td-cust-date font-tabular">
                        <span className="time-cell-text">{formatDate(customer.created_at)}</span>
                      </td>
                      <td className="td-cust-action">
                        <button
                          id={`btn-view-customer-${customer.id}`}
                          type="button"
                          className="btn-action-view"
                          onClick={() => navigate(`/admin/customers/${customer.id}`)}
                          title="View customer fraud profile on dedicated page"
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                            <circle cx="12" cy="12" r="3" />
                          </svg>
                          <span>View Details &rarr;</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

export default AdminCustomers;

