import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
import numpy as np

def load_and_merge_data(transaction_path, identity_path, is_train=True):
    print(f"Loading transaction data from {transaction_path}")
    df_transaction = pd.read_csv(transaction_path)
    
    print(f"Loading identity data from {identity_path}")
    df_identity = pd.read_csv(identity_path)
    
    print("Merging datasets on TransactionID...")
    # Join on TransactionID. Left join preserves all transactions, even if they don't have identity info.
    df = pd.merge(df_transaction, df_identity, on='TransactionID', how='left')
    print(f"Merged dataset shape: {df.shape}")
    return df

def perform_train_val_test_split(df):
    """
    Splits the dataset into train, validation, and test sets BEFORE sampling.
    Returns df_train, df_val, df_test
    """
    print("Performing train/val/test split (70/15/15)...")
    # Time-based split is generally better for transaction data, but we can use random 
    # split for this project assuming TransactionDT isn't strictly sequential over a long period.
    # We will stratify by isFraud to ensure proportional representation.
    df_temp, df_test = train_test_split(df, test_size=0.15, stratify=df['isFraud'], random_state=42)
    df_train, df_val = train_test_split(df_temp, test_size=0.15/0.85, stratify=df_temp['isFraud'], random_state=42)
    
    print(f"Train size: {df_train.shape[0]}, Val size: {df_val.shape[0]}, Test size: {df_test.shape[0]}")
    return df_train, df_val, df_test

def sample_training_data(df_train, fraud_to_legit_ratio=5):
    """
    Downsamples the legitimate transactions to achieve a 1:fraud_to_legit_ratio
    with the fraud transactions. Keeps all fraud transactions.
    """
    print(f"Sampling training data. Target ratio 1:{fraud_to_legit_ratio} (Fraud:Legit)")
    frauds = df_train[df_train['isFraud'] == 1]
    legits = df_train[df_train['isFraud'] == 0]
    
    n_frauds = len(frauds)
    n_legits_to_sample = n_frauds * fraud_to_legit_ratio
    
    # Ensure we don't try to sample more legits than we actually have
    n_legits_to_sample = min(n_legits_to_sample, len(legits))
    
    legits_sampled = legits.sample(n=n_legits_to_sample, random_state=42)
    
    df_sampled = pd.concat([frauds, legits_sampled]).sample(frac=1, random_state=42).reset_index(drop=True)
    print(f"Sampled training data shape: {df_sampled.shape}")
    print(f"Fraud distribution:\n{df_sampled['isFraud'].value_counts()}")
    return df_sampled

def select_features_and_preprocess(df, numerical_cols, categorical_cols, is_train=True, scalers=None, encoders=None):
    """
    Preprocesses the specified columns.
    Handles missing values:
      - Numericals: fill with median (or 0)
      - Categoricals: fill with 'UNKNOWN'
    Scales numericals, encodes categoricals.
    """
    df_processed = df.copy()
    
    if scalers is None:
        scalers = {}
    if encoders is None:
        encoders = {}
        
    # Process Categoricals
    for col in categorical_cols:
        if col not in df_processed.columns:
            continue
        # Fill missing with 'UNKNOWN'
        df_processed[col] = df_processed[col].fillna('UNKNOWN').astype(str)
        
        if is_train:
            encoder = LabelEncoder()
            # Add an 'UNKNOWN' class explicitly
            unique_vals = list(df_processed[col].unique())
            if 'UNKNOWN' not in unique_vals:
                unique_vals.append('UNKNOWN')
            encoder.fit(unique_vals)
            encoders[col] = encoder
        else:
            encoder = encoders.get(col)
            if encoder:
                # Handle unseen labels by mapping them to a known value or 'UNKNOWN' if it was in the training set
                # For simplicity, we just use the encoder but catch unseen. 
                # A more robust way is to append unknown to classes.
                classes = list(encoder.classes_)
                df_processed[col] = df_processed[col].apply(lambda x: x if x in classes else 'UNKNOWN')
        
        if encoder:
            df_processed[col] = encoder.transform(df_processed[col])
            
    # Process Numericals
    for col in numerical_cols:
        if col not in df_processed.columns:
            continue
        # Fill missing with median (0 for simplicity in this baseline)
        # In a real scenario, use median from train set
        df_processed[col] = df_processed[col].fillna(0).astype(float)
        
        if is_train:
            scaler = StandardScaler()
            df_processed[[col]] = scaler.fit_transform(df_processed[[col]])
            scalers[col] = scaler
        else:
            scaler = scalers.get(col)
            if scaler:
                df_processed[[col]] = scaler.transform(df_processed[[col]])

    # Return processed dataframe, keeping TransactionID and isFraud
    cols_to_keep = ['TransactionID'] + (['isFraud'] if 'isFraud' in df.columns else []) + numerical_cols + categorical_cols
    # only keep cols that actually exist in df
    cols_to_keep = [c for c in cols_to_keep if c in df_processed.columns]
    
    return df_processed[cols_to_keep], scalers, encoders
