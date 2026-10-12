import { useEffect, useMemo, useState } from 'react';
import RiskBadge from '../../components/fraud/RiskBadge';
import {
  approveReview,
  getPendingReviews,
  getTransactions,
  rejectReview,
} from '../../services/adminTransactionService';
import { formatCurrency, formatDateTime } from '../../utils/formatters';
import './AdminTransactions.css';

const DECISION_CLASS = { APPROVE: 'badge-low', REVIEW: 'badge-medium', BLOCK: 'badge-high' };
const RISK_FILTERS = [
  { value: 'ALL', label: 'All' },
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
];

function AdminTransactions() {
  const [transactions, setTransactions] = useState([]);
  const [pendingReviews, setPendingReviews] = useState([]);
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewError, setReviewError] = useState(false);
  const [reviewActionId, setReviewActionId] = useState(null);
  const [reviewActionDecision, setReviewActionDecision] = useState(null);
  const [reviewFeedback, setReviewFeedback] = useState(null);
  const [error, setError] = useState(false);

  const loadTransactions = async () => {
    setLoading(true);
    setError(false);
    try {
      setTransactions(await getTransactions());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const loadPendingReviews = async () => {
    setReviewsLoading(true);
    setReviewError(false);
    try {
      setPendingReviews(await getPendingReviews());
    } catch {
      setReviewError(true);
    } finally {
      setReviewsLoading(false);
    }
  };

  const handleReviewDecision = async (transactionId, decision) => {
    setReviewActionId(transactionId);
    setReviewActionDecision(decision);
    setReviewFeedback(null);
    try {
      if (decision === 'APPROVE') await approveReview(transactionId);
      else await rejectReview(transactionId);
      setReviewFeedback({
        type: 'success',
        message: `Transaction ${transactionId} ${decision === 'APPROVE' ? 'approved' : 'rejected'}.`,
      });
      await Promise.all([loadPendingReviews(), loadTransactions()]);
    } catch (actionError) {
      setReviewFeedback({
        type: 'error',
        message: actionError.message || 'Unable to update this review. Refresh the queue and try again.',
      });
    } finally {
      setReviewActionId(null);
      setReviewActionDecision(null);
    }
  };

  useEffect(() => {
    loadTransactions();
    loadPendingReviews();
  }, []);

  const filteredTransactions = useMemo(() => {
    const query = search.trim().toLowerCase();
    return transactions.filter((transaction) => {
      const customer = transaction.customer;
      const matchesSearch = !query || [
        transaction.transaction_id,
        customer?.name,
        customer?.email,
      ].some((value) => String(value ?? '').toLowerCase().includes(query));
      const matchesRisk = riskFilter === 'ALL' || transaction.fraud_prediction?.risk_level === riskFilter;
      return matchesSearch && matchesRisk;
    });
  }, [transactions, search, riskFilter]);

  return (
    <section className="admin-transactions">
      <div className="admin-transactions-heading">
        <div><p className="admin-eyebrow">Account activity</p><h1>Transactions</h1></div>
        <button className="btn btn-secondary" onClick={loadTransactions} disabled={loading}>Refresh</button>
      </div>

      <div className="card admin-review-card">
        <div className="admin-review-heading">
          <div><h2>Pending fraud reviews</h2><p>Review MEDIUM risk transactions before customers can continue to payment.</p></div>
          <button className="btn btn-secondary" onClick={loadPendingReviews} disabled={reviewsLoading}>
            {reviewsLoading ? 'Refreshing...' : 'Refresh reviews'}
          </button>
        </div>
        {reviewFeedback && (
          <p className={`admin-review-feedback admin-review-feedback-${reviewFeedback.type}`} role={reviewFeedback.type === 'error' ? 'alert' : 'status'}>
            {reviewFeedback.message}
          </p>
        )}
        {reviewsLoading ? <p className="admin-transactions-state">Loading pending reviews...</p> : reviewError ? (
          <div className="admin-transactions-state admin-transactions-error">
            <p>Unable to load pending reviews.</p>
            <button className="btn btn-secondary btn-sm" onClick={loadPendingReviews}>Retry</button>
          </div>
        ) : pendingReviews.length === 0 ? (
          <p className="admin-transactions-state">There are no transactions awaiting review.</p>
        ) : (
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Transaction reference</th><th>Customer</th><th>Amount</th><th>Fraud score</th><th>Risk</th><th>Actions</th></tr></thead>
            <tbody>{pendingReviews.map((transaction) => {
              const prediction = transaction.fraud_prediction;
              const customer = transaction.customer;
              const busy = reviewActionId === transaction.transaction_id;
              return <tr key={transaction.transaction_id}>
                <td>TXN-{transaction.transaction_id}</td>
                <td>
                  <div className="admin-review-customer">
                    <span>{customer?.name || 'Customer name unavailable'}</span>
                    <small>{customer?.email || (customer?.user_id ? `User #${customer.user_id}` : 'Customer unavailable')}</small>
                  </div>
                </td>
                <td>{formatCurrency(transaction.amount || 0)}</td>
                <td>{prediction ? prediction.fraud_probability : '—'}</td>
                <td>{prediction ? <RiskBadge riskLevel={prediction.risk_level} /> : '—'}</td>
                <td>
                  <div className="admin-review-actions">
                    <button className="btn btn-primary btn-sm" onClick={() => handleReviewDecision(transaction.transaction_id, 'APPROVE')} disabled={reviewActionId !== null}>
                      {busy && reviewActionDecision === 'APPROVE' ? 'Approving...' : 'Approve'}
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => handleReviewDecision(transaction.transaction_id, 'REJECT')} disabled={reviewActionId !== null}>
                      {busy && reviewActionDecision === 'REJECT' ? 'Rejecting...' : 'Reject'}
                    </button>
                  </div>
                </td>
              </tr>;
            })}</tbody>
          </table></div>
        )}
      </div>

      <div className="card admin-transactions-card">
        <div className="admin-transactions-toolbar">
          <div><h2>All transactions</h2><p>Transactions and available fraud predictions.</p></div>
          <div className="admin-transaction-controls">
            <label className="admin-transaction-search">
              <span className="sr-only">Search transactions or customers</span>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search ID, name, or email" />
            </label>
            <label className="admin-risk-filter">
              <span className="sr-only">Filter transactions by risk</span>
              <select value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}>
                {RISK_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
              </select>
            </label>
          </div>
        </div>

        {loading ? <p className="admin-transactions-state">Loading transactions...</p> : error ? (
          <div className="admin-transactions-state admin-transactions-error">
            <p>Unable to load transactions.</p>
            <button className="btn btn-secondary btn-sm" onClick={loadTransactions}>Retry</button>
          </div>
        ) : filteredTransactions.length === 0 ? <p className="admin-transactions-state">No transactions found.</p> : (
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Transaction ID</th><th>Customer</th><th>Amount</th><th>Status</th><th>Fraud Score</th><th>Risk</th><th>Decision</th><th>Model</th><th>Timestamp</th></tr></thead>
            <tbody>{filteredTransactions.map((transaction) => {
              const prediction = transaction.fraud_prediction;
              return <tr key={transaction.transaction_id}>
                <td>{transaction.transaction_id}</td>
                <td>{transaction.customer ? (transaction.customer.name || transaction.customer.email || `User #${transaction.customer.user_id}`) : 'Unassigned'}</td>
                <td>{formatCurrency(transaction.amount)}</td>
                <td>{transaction.status || '—'}</td>
                <td>{prediction ? prediction.fraud_probability : '—'}</td>
                <td>{prediction ? <RiskBadge riskLevel={prediction.risk_level} /> : '—'}</td>
                <td>{prediction ? <span className={`badge ${DECISION_CLASS[prediction.decision] || 'badge-neutral'}`}>{prediction.decision}</span> : '—'}</td>
                <td>{prediction?.model_used || '—'}</td>
                <td>{formatDateTime(transaction.created_at)}</td>
              </tr>;
            })}</tbody>
          </table></div>
        )}
      </div>
    </section>
  );
}

export default AdminTransactions;
