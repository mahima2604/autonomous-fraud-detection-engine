import os
import torch
import torch.nn.functional as F
from torch.optim import Adam
import joblib

from app.ml.preprocessing import load_and_merge_data, perform_train_val_test_split, sample_training_data, select_features_and_preprocess
from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.model import GraphSAGE
from app.ml.baseline import train_baseline_logistic_regression, evaluate_baseline

def compute_metrics(logits, y, threshold=0.5):
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).long()
    
    tp = ((preds == 1) & (y == 1)).sum().item()
    fp = ((preds == 1) & (y == 0)).sum().item()
    fn = ((preds == 0) & (y == 1)).sum().item()
    tn = ((preds == 0) & (y == 0)).sum().item()
    
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    
    # basic AUC calculation
    try:
        from sklearn.metrics import roc_auc_score
        roc_auc = roc_auc_score(y.cpu().numpy(), probs.detach().cpu().numpy())
    except Exception:
        roc_auc = 0.0
        
    return precision, recall, f1, roc_auc

def train_gnn(data, in_channels, hidden_channels=64, num_layers=2, epochs=50, lr=0.01):
    print("Training GraphSAGE...")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = GraphSAGE(in_channels=in_channels, hidden_channels=hidden_channels, num_layers=num_layers).to(device)
    data = data.to(device)
    
    optimizer = Adam(model.parameters(), lr=lr, weight_decay=5e-4)
    
    # Handle class imbalance using pos_weight
    # pos_weight = negative_samples / positive_samples
    num_pos = data.y.sum().item()
    num_neg = data.y.size(0) - num_pos
    pos_weight = torch.tensor([num_neg / num_pos], dtype=torch.float).to(device) if num_pos > 0 else None
    
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        logits = model(data.x, data.edge_index)
        loss = criterion(logits, data.y.float())
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 10 == 0 or epoch == 0:
            precision, recall, f1, auc = compute_metrics(logits, data.y)
            print(f"Epoch {epoch+1:03d} | Loss: {loss.item():.4f} | F1: {f1:.4f} | AUC: {auc:.4f}")
            
    return model

def evaluate_gnn(model, data):
    print("\nEvaluating GraphSAGE on VALIDATION set...")
    model.eval()
    device = next(model.parameters()).device
    data = data.to(device)
    
    with torch.no_grad():
        logits = model(data.x, data.edge_index)
        probs = torch.sigmoid(logits)
        preds = (probs > 0.5).long()
        
    y = data.y
    
    tp = ((preds == 1) & (y == 1)).sum().item()
    fp = ((preds == 1) & (y == 0)).sum().item()
    fn = ((preds == 0) & (y == 1)).sum().item()
    tn = ((preds == 0) & (y == 0)).sum().item()
    
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    
    try:
        from sklearn.metrics import roc_auc_score
        roc_auc = roc_auc_score(y.cpu().numpy(), probs.cpu().numpy())
    except Exception:
        roc_auc = 0.0
        
    print(f"  VALIDATION PRECISION: {precision:.4f}")
    print(f"  VALIDATION RECALL: {recall:.4f}")
    print(f"  VALIDATION F1: {f1:.4f}")
    print(f"  VALIDATION ROC_AUC: {roc_auc:.4f}")
    print(f"  VALIDATION Confusion Matrix:\n[[{tn} {fp}]\n [{fn} {tp}]]\n")
    return precision, recall, f1, roc_auc

def save_artifacts(model, baseline_model, scalers, encoders, output_dir="models"):
    print(f"Saving models and artifacts to {output_dir}/")
    os.makedirs(output_dir, exist_ok=True)
    
    if model is not None:
        torch.save(model.state_dict(), os.path.join(output_dir, "graphsage.pth"))
    if baseline_model is not None:
        joblib.dump(baseline_model, os.path.join(output_dir, "logistic_regression.pkl"))
    if scalers is not None:
        joblib.dump(scalers, os.path.join(output_dir, "scalers.pkl"))
    if encoders is not None:
        joblib.dump(encoders, os.path.join(output_dir, "encoders.pkl"))
    print("Saved successfully.")

if __name__ == "__main__":
    # Define paths
    TX_PATH = "../data/train_transaction.csv"
    ID_PATH = "../data/train_identity.csv"
    
    # Feature Selection (Practical Subset)
    # Using key numerical and categorical features that realistically impact fraud
    NUMERICAL_COLS = ['TransactionAmt', 'dist1', 'dist2', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10', 'C11', 'C12', 'C13', 'C14']
    CATEGORICAL_COLS = ['ProductCD', 'card1', 'card2', 'card3', 'card4', 'card5', 'card6', 'addr1', 'addr2', 'P_emaildomain', 'R_emaildomain', 'DeviceType', 'DeviceInfo']
    
    # Meaningful shared identifiers to create graph edges
    EDGE_COLS = ['card1', 'addr1', 'P_emaildomain', 'DeviceInfo']

    # 1. Load Data
    df = load_and_merge_data(TX_PATH, ID_PATH)
    
    # 2. Split (prevent leakage)
    df_train_full, df_val, df_test = perform_train_val_test_split(df)
    
    # 3. Sample training data to handle imbalance (1:5 ratio)
    df_train_sampled = sample_training_data(df_train_full, fraud_to_legit_ratio=5)
    
    # 4. Preprocess (Fit on Train, Transform others)
    print("Preprocessing training set...")
    df_train_proc, scalers, encoders = select_features_and_preprocess(
        df_train_sampled, NUMERICAL_COLS, CATEGORICAL_COLS, is_train=True
    )
    
    print("Preprocessing validation set...")
    df_val_proc, _, _ = select_features_and_preprocess(
        df_val, NUMERICAL_COLS, CATEGORICAL_COLS, is_train=False, scalers=scalers, encoders=encoders
    )
    
    # 5. Baseline Model
    features_for_baseline = NUMERICAL_COLS + CATEGORICAL_COLS
    X_train = df_train_proc[features_for_baseline].values
    y_train = df_train_proc['isFraud'].values
    
    X_val = df_val_proc[features_for_baseline].values
    y_val = df_val_proc['isFraud'].values
    
    clf = train_baseline_logistic_regression(X_train, y_train)
    evaluate_baseline(clf, X_val, y_val)
    
    # Save artifacts before graph construction in case of memory errors
    save_artifacts(None, clf, scalers, encoders, output_dir="models")
    
    # 6. Graph Construction (Train)
    train_data = build_homogeneous_transaction_graph(df_train_proc, features_for_baseline, EDGE_COLS)
    
    # 7. Train GNN
    in_channels = len(features_for_baseline)
    gnn_model = train_gnn(train_data, in_channels, hidden_channels=64, num_layers=2, epochs=100, lr=0.01)
    
    # 8. Evaluate GNN on Validation Set
    val_data = build_homogeneous_transaction_graph(df_val_proc, features_for_baseline, EDGE_COLS)
    evaluate_gnn(gnn_model, val_data)
    
    # 9. Save artifacts
    save_artifacts(gnn_model, clf, scalers, encoders, output_dir="models")

