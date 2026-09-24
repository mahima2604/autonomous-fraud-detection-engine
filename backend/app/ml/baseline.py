from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix

def train_baseline_logistic_regression(X_train, y_train, class_weight='balanced'):
    print("Training Logistic Regression baseline...")
    clf = LogisticRegression(class_weight=class_weight, max_iter=3000, random_state=42)
    clf.fit(X_train, y_train)
    return clf

def evaluate_baseline(clf, X_test, y_test):
    print("Evaluating Logistic Regression baseline...")
    y_pred = clf.predict(X_test)
    y_prob = clf.predict_proba(X_test)[:, 1]
    
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    
    try:
        roc_auc = roc_auc_score(y_test, y_prob)
    except ValueError:
        roc_auc = 0.0 # Handle case with only one class in test
        
    cm = confusion_matrix(y_test, y_pred)
    
    metrics = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc,
        "confusion_matrix": cm.tolist()
    }
    
    for k, v in metrics.items():
        if k != "confusion_matrix":
            print(f"  {k.upper()}: {v:.4f}")
    print(f"  Confusion Matrix:\n{cm}")
    
    return metrics
