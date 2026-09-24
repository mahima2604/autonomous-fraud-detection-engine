import networkx as nx
import torch
from torch_geometric.data import Data
from torch_geometric.utils import from_networkx
import pandas as pd
import numpy as np

def analyze_cardinality(df, edge_cols, max_cardinality=10000):
    """
    Analyzes the cardinality of potential edge columns.
    If a value appears more than `max_cardinality` times, we might want to ignore it 
    when building the graph to prevent "super-nodes" that connect everything.
    """
    print(f"Analyzing cardinality for edges. Max allowed frequency: {max_cardinality}")
    valid_values_map = {}
    for col in edge_cols:
        if col in df.columns:
            counts = df[col].value_counts()
            # Keep only values that appear more than once (to form an edge) but less than max_cardinality
            valid_values = counts[(counts > 1) & (counts <= max_cardinality)].index.tolist()
            valid_values_map[col] = set(valid_values)
            print(f"  {col}: {len(valid_values)} valid shared values out of {len(counts)} unique values.")
    return valid_values_map

def build_homogeneous_transaction_graph(df, feature_cols, edge_cols, max_cardinality=10000):
    """
    Builds a homogeneous graph using PyTorch Geometric where nodes are transactions.
    Edges are formed between transactions that share the same valid identifier in edge_cols.
    """
    print("Building homogeneous transaction graph...")
    
    # Ensure dataframe index is 0 to N-1 to align with node feature tensor indices
    df = df.reset_index(drop=True)
    
    # 1. Analyze cardinality to get valid values for edges
    valid_values_map = analyze_cardinality(df, edge_cols, max_cardinality)
    
    # 2. Extract node features
    # df is expected to be already preprocessed (scaled, encoded)
    # Ensure order is preserved. We'll use the df index as the node index.
    node_features = df[feature_cols].values
    x = torch.tensor(node_features, dtype=torch.float)
    
    # Extract labels if available
    if 'isFraud' in df.columns:
        y = torch.tensor(df['isFraud'].values, dtype=torch.long)
    else:
        y = None
        
    transaction_ids = df['TransactionID'].values

    # 3. Build edges
    # For a homogeneous graph, we connect transaction i to transaction j
    # if they share a common value in any of the edge_cols.
    # To prevent edge explosion (MemoryError), we use a bounded-neighbor approach:
    # A node connects to at most `max_neighbors` other nodes in the same group.
    max_neighbors = 10
    print(f"Edge-limiting strategy: bounded-neighbor (max_neighbors={max_neighbors})")
    
    edge_u = []
    edge_v = []
    
    for col in edge_cols:
        if col not in df.columns:
            continue
        
        valid_vals = valid_values_map.get(col, set())
        
        df_valid = df[df[col].isin(valid_vals)].copy()
        df_valid['node_idx'] = df_valid.index
        
        grouped = df_valid.groupby(col)['node_idx'].apply(lambda x: x.values)
        
        for val, indices in grouped.items():
            n = len(indices)
            if n > 1:
                # Bounded neighbors
                k = min(n - 1, max_neighbors)
                for i in range(n):
                    u = indices[i]
                    for step in range(1, k + 1):
                        v = indices[(i + step) % n]
                        edge_u.append(u)
                        edge_v.append(v)
                        edge_u.append(v)
                        edge_v.append(u)
    
    if not edge_u:
        print("Warning: No edges found. Graph will have only isolated nodes.")
        edge_index = torch.empty((2, 0), dtype=torch.long)
    else:
        # Convert to tensor and remove duplicates
        edge_index = torch.tensor([edge_u, edge_v], dtype=torch.long)
        edge_index = torch.unique(edge_index, dim=1)
        
    print(f"Graph built with {x.shape[0]} nodes and {edge_index.shape[1]} edges.")
    
    data = Data(x=x, edge_index=edge_index, y=y)
    data.transaction_ids = transaction_ids # keep for reference
    
    return data
