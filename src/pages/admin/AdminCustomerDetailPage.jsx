// AdminCustomerDetailPage.jsx
// Dedicated full-page view for individual Customer Profiles and historical fraud assessment history.

import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getCustomerDetails } from '../../services/adminCustomerService';
import RiskBadge from '../../components/fraud/RiskBadge';
import { formatCurrency, formatDate, formatDateTime } from '../../utils/formatters';
import './AdminCustomerDetailPage.css';

const DECISION_CLASS = {
  APPROVE: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCK: 'badge-high',
};

function AdminCustomerDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchCustomer = async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await getCustomerDetails(id);
      setDetails(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCustomer();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleBack = () => {
    navigate('/admin/customers');
  };

  return (
    <div className="admin-customer-detail-page">
      {/* Top Header */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <button
              type="button"
              onClick={handleBack}
              className="admin-back-btn"
              title="Return to customer directory"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              <span>Customers</span>
            </button>
            <span className="admin-kicker-separator">/</span>
            <span className="admin-kicker-dot" />
            <span>USR-#{id} &middot; Customer Fraud Profile</span>
          </div>

          <h1 className="admin-page-title">
            {details?.customer ? `${details.customer.name || 'Customer'} (USR-#${id})` : `Customer Account USR-#${id}`}
          </h1>
          <p className="admin-page-subtitle">
            Customer account registration records, verified email identity, and chronological transaction fraud risk assessments.
          </p>
        </div>

        <div className="admin-header-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleBack}
          >
            &larr; Back to Directory
          </button>
        </div>
      </div>

      {/* Main Body */}
      {loading ? (
        <div className="card admin-page-state">
          <div className="spinner spinner-dark" />
          <p>Loading customer profile and associated transaction history...</p>
        </div>
      ) : error || !details ? (
        <div className="card admin-page-state admin-table-error" role="alert">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <p>Unable to retrieve customer details for ID USR-#{id}.</p>
          <button className="btn btn-secondary btn-sm" onClick={fetchCustomer}>
            Retry
          </button>
        </div>
      ) : (
        <div className="admin-customer-detail-body">
          {/* Profile Overview Card */}
          <div className="card admin-profile-card">
            <div className="card-header">
              <span className="explanation-badge">ACCOUNT IDENTITY</span>
              <h2 className="admin-card-title">Registration & Identity Summary</h2>
            </div>

            <div className="admin-customer-profile-grid">
              <div className="profile-stat-box">
                <span className="profile-stat-label">Full Name</span>
                <strong className="profile-stat-value">{details.customer.name || 'Not provided'}</strong>
              </div>
              <div className="profile-stat-box">
                <span className="profile-stat-label">Email Address</span>
                <strong className="profile-stat-value">{details.customer.email}</strong>
              </div>
              <div className="profile-stat-box">
                <span className="profile-stat-label">Account Status</span>
                <strong className="profile-stat-value">
                  <span className={`badge ${details.customer.is_active ? 'badge-low' : 'badge-neutral'}`}>
                    {details.customer.is_active ? 'Active Customer' : 'Inactive'}
                  </span>
                </strong>
              </div>
              <div className="profile-stat-box">
                <span className="profile-stat-label">Registration Date</span>
                <strong className="profile-stat-value font-tabular">
                  {formatDate(details.customer.created_at)}
                </strong>
              </div>
              <div className="profile-stat-box">
                <span className="profile-stat-label">Total Transactions</span>
                <strong className="profile-stat-value font-tabular">
                  {details.transactions ? details.transactions.length : 0} orders
                </strong>
              </div>
            </div>
          </div>

          {/* Transaction & Fraud Risk History */}
          <div className="card admin-history-card">
            <div className="card-header">
              <div>
                <span className="explanation-badge">ACTIVITY AUDIT</span>
                <h2 className="admin-card-title">Transaction & Fraud Risk History</h2>
              </div>
              <p className="admin-card-description">
                All checkout events and real-time ML risk predictions recorded for this customer.
              </p>
            </div>

            <div className="admin-table-scroll-container">
              <table className="admin-table admin-cust-history-table">
                <thead>
                  <tr>
                    <th>Transaction ID</th>
                    <th>Amount</th>
                    <th>Fraud Score</th>
                    <th>Risk Level</th>
                    <th>Model Decision</th>
                    <th>Model Version</th>
                    <th>Assessed At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {!details.transactions || details.transactions.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="admin-table-empty">
                        No transactions recorded yet for this customer account.
                      </td>
                    </tr>
                  ) : (
                    details.transactions.map((transaction) => {
                      const prediction = transaction.fraud_prediction;

                      return (
                        <tr key={transaction.transaction_id}>
                          <td>
                            <span className="admin-txn-id">TXN-{transaction.transaction_id}</span>
                          </td>
                          <td className="font-tabular">
                            <strong>{formatCurrency(transaction.amount)}</strong>
                          </td>
                          {prediction ? (
                            <>
                              <td className="font-tabular">
                                <span className="risk-score-value">
                                  {Number(prediction.fraud_probability).toFixed(4)}
                                </span>
                              </td>
                              <td>
                                <RiskBadge riskLevel={prediction.risk_level} />
                              </td>
                              <td>
                                <span className={`badge ${DECISION_CLASS[prediction.decision] || 'badge-neutral'}`}>
                                  {prediction.decision}
                                </span>
                              </td>
                              <td>
                                <span className="model-tag">{prediction.model_used || '—'}</span>
                              </td>
                              <td className="font-tabular">
                                <span className="time-cell-text">{formatDateTime(prediction.created_at)}</span>
                              </td>
                              <td>
                                <button
                                  type="button"
                                  className="btn-action-explain"
                                  onClick={() => navigate(`/admin/transactions/${transaction.transaction_id}/explanation`)}
                                  title="View model explanation for this transaction"
                                >
                                  <span>Explain &rarr;</span>
                                </button>
                              </td>
                            </>
                          ) : (
                            <>
                              <td colSpan="5" className="text-muted">
                                No fraud prediction recorded. (Created: {formatDateTime(transaction.created_at)})
                              </td>
                              <td>—</td>
                            </>
                          )}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AdminCustomerDetailPage;
