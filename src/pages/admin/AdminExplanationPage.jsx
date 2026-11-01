// AdminExplanationPage.jsx
// Dedicated full-page shell for Deep Prediction Analysis and Fraud Investigation.

import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import PredictionExplanation from '../../components/admin/PredictionExplanation';
import { getTransactions } from '../../services/adminTransactionService';
import './AdminExplanationPage.css';

function AdminExplanationPage() {
  const { transactionId } = useParams();
  const navigate = useNavigate();

  const [transactions, setTransactions] = useState([]);
  const [selectedTxId, setSelectedTxId] = useState(transactionId || null);
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    getTransactions()
      .then((data) => {
        if (!active) return;
        const list = Array.isArray(data) ? data : [];
        setTransactions(list);
        if (!transactionId && list.length > 0) {
          setSelectedTxId(list[0].transaction_id);
        }
      })
      .catch(() => {
        if (active) setListError(true);
      })
      .finally(() => {
        if (active) setLoadingList(false);
      });

    return () => {
      active = false;
    };
  }, [transactionId]);

  useEffect(() => {
    if (transactionId) {
      setSelectedTxId(transactionId);
    }
  }, [transactionId]);

  const activeTxId = transactionId || selectedTxId;

  const handleBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/admin/dashboard');
    }
  };

  const handleSelectTransaction = (newTxId) => {
    setSelectedTxId(newTxId);
    navigate(`/admin/transactions/${newTxId}/explanation`);
  };

  const currentTx = transactions.find((t) => String(t.transaction_id) === String(activeTxId)) || null;

  return (
    <div className="admin-explanation-page">
      {/* Top Nav Control Bar */}
      <div className="admin-page-nav-bar">
        <button
          type="button"
          onClick={handleBack}
          className="admin-back-btn"
          title="Return to previous screen"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          <span>Back to Dashboard</span>
        </button>

        {transactions.length > 0 && (
          <div className="admin-transaction-picker">
            <label htmlFor="admin-tx-select" className="admin-picker-label">
              Switch Transaction:
            </label>
            <select
              id="admin-tx-select"
              className="admin-select admin-tx-select"
              value={activeTxId || ''}
              onChange={(e) => handleSelectTransaction(e.target.value)}
              aria-label="Select transaction for fraud investigation"
            >
              {transactions.map((tx) => {
                const pred = tx.fraud_prediction;
                const customerName = tx.customer?.name || (tx.customer?.user_id ? `User #${tx.customer.user_id}` : 'Customer');
                const riskLevel = pred?.risk_level || 'UNKNOWN';
                const reviewDecision = tx.review_decision ? ` · ${tx.review_decision}` : (tx.status === 'REVIEW' ? ' · PENDING' : '');
                return (
                  <option key={tx.transaction_id} value={tx.transaction_id}>
                    TXN-{tx.transaction_id} &middot; {customerName} &middot; ${Number(tx.amount || 0).toFixed(2)} &middot; {riskLevel}{reviewDecision}
                  </option>
                );
              })}
            </select>
          </div>
        )}
      </div>

      {/* Main Investigation Content */}
      <div className="admin-explanation-page-body">
        {activeTxId ? (
          <PredictionExplanation
            key={activeTxId}
            transactionId={activeTxId}
            transactionSummary={currentTx}
          />
        ) : loadingList ? (
          <div className="admin-explanation-state">
            <div className="spinner spinner-dark" />
            <p>Loading transaction investigation...</p>
          </div>
        ) : listError ? (
          <div className="admin-explanation-state">
            <p>Unable to retrieve transaction records.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
              Retry
            </button>
          </div>
        ) : (
          <div className="admin-explanation-state">
            <p>No transactions recorded yet in the database.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default AdminExplanationPage;
