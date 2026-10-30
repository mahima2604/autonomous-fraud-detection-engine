// AdminExplanationPage.jsx
// Dedicated full-page view for Deep Prediction Analysis and Machine Learning Attribution.

import { useParams, useNavigate } from 'react-router-dom';
import PredictionExplanation from '../../components/admin/PredictionExplanation';
import './AdminExplanationPage.css';

function AdminExplanationPage() {
  const { transactionId } = useParams();
  const navigate = useNavigate();

  const handleBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/admin/dashboard');
    }
  };

  return (
    <div className="admin-explanation-page">
      {/* Top Navigation & Breadcrumbs */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <button
              type="button"
              onClick={handleBack}
              className="admin-back-btn"
              title="Return to previous overview"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              <span>Back</span>
            </button>
            <span className="admin-kicker-separator">/</span>
            <span className="admin-kicker-dot" />
            <span>Fraud Intelligence &middot; ML Explainability</span>
          </div>

          <h1 className="admin-page-title">
            Deep Prediction Analysis: TXN-{transactionId}
          </h1>
          <p className="admin-page-subtitle">
            Comprehensive breakdown of evaluated risk score, decision boundaries, ingested features, and model interpretability.
          </p>
        </div>

        <div className="admin-header-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleBack}
          >
            &larr; Back to Dashboard
          </button>
        </div>
      </div>

      {/* Main Attribution Component Card */}
      <div className="admin-explanation-page-body">
        <PredictionExplanation transactionId={transactionId} />
      </div>
    </div>
  );
}

export default AdminExplanationPage;
