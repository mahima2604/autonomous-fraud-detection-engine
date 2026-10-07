import { useEffect, useMemo, useState } from 'react';
import RiskBadge from '../../components/fraud/RiskBadge';
import { getTransactions } from '../../services/adminTransactionService';
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
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');
  const [loading, setLoading] = useState(true);
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

  useEffect(() => { loadTransactions(); }, []);

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
