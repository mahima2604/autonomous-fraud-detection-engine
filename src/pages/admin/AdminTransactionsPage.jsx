// AdminTransactionsPage.jsx
// Enterprise transaction audit log with manual review decisions and model predictions.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import RiskBadge from '../../components/fraud/RiskBadge';
import { approveReview, getTransactions, rejectReview } from '../../services/adminTransactionService';
import { formatCurrency, formatDateTime } from '../../utils/formatters';
import './AdminTransactions.css';


const DECISION_CLASS = {
  APPROVE: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCK: 'badge-high',
};

const STATUS_CLASS = {
  COMPLETED: 'badge-low',
  PAID: 'badge-low',
  REVIEW_APPROVED: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCKED: 'badge-high',
  REJECTED: 'badge-high',
};

const STATUS_LABELS = {
  COMPLETED: 'Completed',
  PAID: 'Paid',
  REVIEW_APPROVED: 'Review Approved',
  REVIEW: 'Review Hold',
  BLOCKED: 'Blocked',
  REJECTED: 'Rejected',
};

const RISK_FILTERS = [
  { value: 'ALL', label: 'All Risk Levels' },
  { value: 'LOW', label: 'Low Risk' },
  { value: 'MEDIUM', label: 'Medium Risk' },
  { value: 'HIGH', label: 'High Risk' },
];

function AdminTransactionsPage() {
  const navigate = useNavigate();
  const [transactions, setTransactions] = useState([]);
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reviewActionId, setReviewActionId] = useState(null);
  const [reviewActionDecision, setReviewActionDecision] = useState(null);
  const [reviewFeedback, setReviewFeedback] = useState(null);

  async function loadTransactions() {
    setLoading(true);
    setError(false);
    try {
      const data = await getTransactions();
      setTransactions(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  async function handleReviewDecision(transactionId, decision) {
    setReviewActionId(transactionId);
    setReviewActionDecision(decision);
    setReviewFeedback(null);
    try {
      if (decision === 'APPROVE') {
        await approveReview(transactionId);
      } else {
        await rejectReview(transactionId);
      }
      setReviewFeedback({
        type: 'success',
        message: `Transaction TXN-${transactionId} was successfully ${decision === 'APPROVE' ? 'approved' : 'rejected'}. Customer status updated.`,
      });
      await loadTransactions();
    } catch (actionError) {
      setReviewFeedback({
        type: 'error',
        message: actionError.message || 'Unable to update review decision. Please try again.',
      });
    } finally {
      setReviewActionId(null);
      setReviewActionDecision(null);
    }
  }

  useEffect(() => {
    loadTransactions();
  }, []);

  const filteredTransactions = useMemo(() => {
    const query = search.trim().toLowerCase();
    return transactions.filter((transaction) => {
      const matchesSearch = !query || [
        transaction.transaction_id,
        transaction.customer?.name,
        transaction.customer?.email,
        transaction.order_id,
      ].some((value) => String(value ?? '').toLowerCase().includes(query));

      const matchesRisk = riskFilter === 'ALL' || transaction.fraud_prediction?.risk_level === riskFilter;
      return matchesSearch && matchesRisk;
    });
  }, [transactions, search, riskFilter]);

  const pendingReviewCount = useMemo(() => {
    return transactions.filter(
      (t) => t.status === 'REVIEW' && t.fraud_prediction?.decision === 'REVIEW',
    ).length;
  }, [transactions]);

  return (
    <section className="admin-transactions">
      {/* Page Header */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <span className="admin-kicker-dot" />
            <span>Audit & Decision Queue</span>
          </div>
          <h1 className="admin-page-title">Transaction History & Reviews</h1>
          <p className="admin-page-subtitle">
            Comprehensive audit log of all transactions assessed by the fraud engine, with administrative review actions.
          </p>
        </div>
        <div className="admin-header-actions">
          <button
            id="admin-transactions-refresh-btn"
            className="btn btn-secondary admin-refresh-btn"
            onClick={loadTransactions}
            disabled={loading}
            title="Refresh transactions log"
          >
            <svg
              className={`admin-refresh-icon ${loading ? 'spinning' : ''}`}
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
            <span>{loading ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Review Feedback Alert */}
      {reviewFeedback && (
        <div
          className={`admin-alert-banner admin-alert-${reviewFeedback.type === 'error' ? 'danger' : 'success'}`}
          role={reviewFeedback.type === 'error' ? 'alert' : 'status'}
        >
          {reviewFeedback.type === 'success' ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          )}
          <div className="admin-alert-content">
            {reviewFeedback.message}
          </div>
          <button
            type="button"
            className="btn-close-alert"
            onClick={() => setReviewFeedback(null)}
            title="Dismiss notice"
          >
            &times;
          </button>
        </div>
      )}

      {/* Main Table Card */}
      <div className="card admin-table-card">
        <div className="admin-table-toolbar">
          <div className="admin-toolbar-title-wrap">
            <div className="admin-title-badge-row">
              <h2 className="admin-card-title">All Transactions</h2>
              {pendingReviewCount > 0 && (
                <span className="badge badge-medium" title="Transactions currently awaiting admin review decision">
                  {pendingReviewCount} Action Required
                </span>
              )}
            </div>
            <p className="admin-card-description">
              Showing {filteredTransactions.length} of {transactions.length} total transactions.
            </p>
          </div>

          <div className="admin-toolbar-controls">
            <div className="admin-search-wrapper">
              <svg className="admin-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                id="admin-transactions-search"
                type="text"
                className="admin-input admin-search-input"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search ID, customer, email, order..."
              />
              {search && (
                <button
                  type="button"
                  className="admin-search-clear"
                  onClick={() => setSearch('')}
                  title="Clear search"
                >
                  &times;
                </button>
              )}
            </div>

            <select
              id="admin-transactions-risk-filter"
              className="admin-select"
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              aria-label="Filter transactions by risk level"
            >
              {RISK_FILTERS.map((filter) => (
                <option key={filter.value} value={filter.value}>
                  {filter.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div className="admin-table-state">
            <div className="spinner spinner-dark" />
            <p>Loading transactions and risk assessments...</p>
          </div>
        ) : error ? (
          <div className="admin-table-state admin-table-error">
            <p>Unable to retrieve transaction records.</p>
            <button className="btn btn-secondary btn-sm" onClick={loadTransactions}>
              Retry
            </button>
          </div>
        ) : filteredTransactions.length === 0 ? (
          <div className="admin-table-state">
            <p>
              {transactions.length === 0
                ? 'No transactions recorded yet in the database.'
                : 'No transactions match the selected filter criteria.'}
            </p>
          </div>
        ) : (
          <>
            <div className="admin-table-scroll-container">
              <table className="admin-table admin-transactions-table">
                <thead>
                  <tr>
                    <th className="th-txid">Transaction ID</th>
                    <th className="th-date">Date / Time</th>
                    <th className="th-amount">Amount</th>
                    <th className="th-customer">Customer & Order</th>
                    <th className="th-status">Checkout Status</th>
                    <th className="th-review">Review Status</th>
                    <th className="th-score">Risk Score</th>
                    <th className="th-risk">Risk Category</th>
                    <th className="th-decision">Model Decision</th>
                    <th className="th-actions">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTransactions.map((transaction) => {
                    const prediction = transaction.fraud_prediction;
                    const pendingReview = transaction.status === 'REVIEW' && prediction?.decision === 'REVIEW';
                    const isBusy = reviewActionId === transaction.transaction_id;

                    return (
                      <tr
                        key={transaction.transaction_id}
                        className={pendingReview ? 'row-pending-review' : ''}
                      >
                        <td className="td-txid">
                          <span className="admin-txn-id">TXN-{transaction.transaction_id}</span>
                        </td>
                        <td className="td-date font-tabular">
                          <span className="time-cell-text">{formatDateTime(transaction.created_at)}</span>
                        </td>
                        <td className="td-amount font-tabular">
                          <strong>{formatCurrency(transaction.amount)}</strong>
                        </td>
                        <td className="td-customer">
                          <div className="admin-customer-cell">
                            <span className="customer-name">
                              {transaction.customer?.name ||
                                transaction.customer?.email ||
                                (transaction.customer?.user_id
                                  ? `User #${transaction.customer.user_id}`
                                  : 'Unassigned')}
                            </span>
                            <span className="customer-order">
                              {transaction.order_id ? `Order #${transaction.order_id}` : 'No order link'}
                            </span>
                          </div>
                        </td>
                        <td className="td-status">
                          <span className={`badge ${STATUS_CLASS[transaction.status] || 'badge-neutral'}`}>
                            {STATUS_LABELS[transaction.status] || transaction.status || '—'}
                          </span>
                        </td>
                        <td className="td-review">
                          {transaction.review_decision === 'APPROVE' ? (
                            <div className="review-status-cell">
                              <span className="badge badge-low">Approved</span>
                              {transaction.reviewed_at && (
                                <span className="reviewed-timestamp">{formatDateTime(transaction.reviewed_at)}</span>
                              )}
                            </div>
                          ) : transaction.review_decision === 'REJECT' ? (
                            <div className="review-status-cell">
                              <span className="badge badge-high">Rejected</span>
                              {transaction.reviewed_at && (
                                <span className="reviewed-timestamp">{formatDateTime(transaction.reviewed_at)}</span>
                              )}
                            </div>
                          ) : pendingReview ? (
                            <span className="badge badge-medium">Pending Review</span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="td-score font-tabular">
                          <span className="risk-score-value">
                            {prediction ? Number(prediction.fraud_probability).toFixed(4) : '—'}
                          </span>
                        </td>
                        <td className="td-risk">
                          {prediction ? <RiskBadge riskLevel={prediction.risk_level} /> : <span className="text-muted">—</span>}
                        </td>
                        <td className="td-decision">
                          {prediction ? (
                            <span className={`badge ${DECISION_CLASS[prediction.decision] || 'badge-neutral'}`}>
                              {prediction.decision}
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="td-actions">
                          <div className="admin-row-actions">
                            {pendingReview && (
                              <div className="admin-review-buttons">
                                <button
                                  id={`btn-approve-txn-${transaction.transaction_id}`}
                                  type="button"
                                  className="btn-review-approve"
                                  onClick={() => handleReviewDecision(transaction.transaction_id, 'APPROVE')}
                                  disabled={isBusy}
                                  title="Approve transaction and allow payment"
                                >
                                  {isBusy && reviewActionDecision === 'APPROVE' ? 'Approving...' : 'Approve'}
                                </button>
                                <button
                                  id={`btn-reject-txn-${transaction.transaction_id}`}
                                  type="button"
                                  className="btn-review-reject"
                                  onClick={() => handleReviewDecision(transaction.transaction_id, 'REJECT')}
                                  disabled={isBusy}
                                  title="Reject transaction due to fraud suspicion"
                                >
                                  {isBusy && reviewActionDecision === 'REJECT' ? 'Rejecting...' : 'Reject'}
                                </button>
                              </div>
                            )}

                            {prediction && (
                              <button
                                id={`btn-explain-txn-${transaction.transaction_id}`}
                                type="button"
                                className="btn-action-explain"
                                onClick={() =>
                                  navigate(`/admin/transactions/${transaction.transaction_id}/explanation`)
                                }
                                title="Open detailed explanation page"
                              >
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                  <polyline points="9 18 15 12 9 6" />
                                </svg>
                                <span>Explain &rarr;</span>
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export default AdminTransactionsPage;
