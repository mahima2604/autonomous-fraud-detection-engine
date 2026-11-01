"""Central score bands and checkout actions.

The score cutoffs are policy thresholds, not calibrated fraud probabilities.
They remain configurable through the existing environment variables.
"""

import math
import os


FRAUD_REVIEW_THRESHOLD = float(os.getenv("FRAUD_REVIEW_THRESHOLD", "0.30"))
FRAUD_BLOCK_THRESHOLD = float(os.getenv("FRAUD_BLOCK_THRESHOLD", "0.70"))
if not (0 < FRAUD_REVIEW_THRESHOLD < FRAUD_BLOCK_THRESHOLD < 1):
    raise RuntimeError("Fraud thresholds must satisfy 0 < review < block < 1")


def classify_score(score):
    """Return the immutable model-score risk band and score-based outcome."""
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("The fraud model returned an invalid probability")
    if score <= FRAUD_REVIEW_THRESHOLD:
        return "LOW", "APPROVE"
    if score <= FRAUD_BLOCK_THRESHOLD:
        return "MEDIUM", "REVIEW"
    return "HIGH", "BLOCK"


def checkout_decision(score, verification_signals=None):
    """Return the backend operational action for a checkout.

    Every checkout transaction requires mandatory administrator review.
    OTP verification and address confirmation provide evidence for the
    reviewing administrator, but do not automatically approve the transaction.
    """
    risk_level, _score_outcome = classify_score(score)
    return risk_level, "REVIEW"


def medium_requires_targeted_review(address_account_checks):
    """Hold a verified medium checkout when matching-address delivery failures exist.

    The stored order statuses are contextual evidence, not proof of fraud. Other
    address/account counts and incomplete graph topology have no validated cutoff
    here and therefore do not independently prevent release.
    """
    history = (address_account_checks or {}).get("account_history") or {}
    outcomes = history.get("recorded_cancellation_or_delivery_failure_status_counts") or {}
    return any(type(count) is int and count > 0 for count in outcomes.values())

