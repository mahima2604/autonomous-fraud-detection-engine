// Orders.jsx — user order history.
import { useEffect, useState } from 'react';
import { getOrders } from '../services/orderService';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';
import { formatCurrency, formatDate } from '../utils/formatters';

const STATUS_CLASS = {
  DELIVERED: 'badge-low',
  SHIPPED: 'badge-medium',
  PROCESSING: 'badge-medium',
  CANCELLED: 'badge-high',
};

function Orders() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    getOrders()
      .then((data) => active && setOrders(data))
      .catch((err) => active && setError(err.message || 'Failed to load orders.'))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <LoadingSpinner label="Loading your orders…" />;
  if (error) return <EmptyState title="Something went wrong" message={error} />;
  if (orders.length === 0) return <EmptyState title="No orders yet" message="Your past orders will show up here." />;

  return (
    <div>
      <h1>Order History</h1>
      <p className="mock-note">This demo order history uses sample data and is not linked to your account.</p>
      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Order ID</th>
              <th>Date</th>
              <th>Items</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Payment</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.id}>
                <td>{order.id}</td>
                <td>{formatDate(order.date)}</td>
                <td>{order.items?.join(', ')}</td>
                <td>{formatCurrency(order.amount)}</td>
                <td><span className={`badge ${STATUS_CLASS[order.status] || 'badge-neutral'}`}>{order.status}</span></td>
                <td>{order.paymentStatus}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Orders;
