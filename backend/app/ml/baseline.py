from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer

def train_baseline_logistic_regression(df_train, y_train, numerical_cols, categorical_cols, class_weight='balanced'):
    print("Training Logistic Regression baseline...")
    
    numerical_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='constant', fill_value=0.0)),
        ('scaler', StandardScaler())
    ])
    
    categorical_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='constant', fill_value='UNKNOWN')),
        ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))
    ])
    
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numerical_transformer, numerical_cols),
            ('cat', categorical_transformer, categorical_cols)
        ]
    )
    
    clf = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('classifier', LogisticRegression(class_weight=class_weight, max_iter=3000, random_state=42))
    ])
    
    # Fit the pipeline on the dataframe columns
    clf.fit(df_train[[*numerical_cols, *categorical_cols]], y_train)
    return clf

def evaluate_baseline(clf, df_test, y_test, numerical_cols, categorical_cols):
    print("Evaluating Logistic Regression baseline...")
    X_test = df_test[[*numerical_cols, *categorical_cols]]
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
