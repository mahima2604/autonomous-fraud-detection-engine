"""Causal transaction graph construction shared by training and serving."""

import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data


def build_homogeneous_transaction_graph(
    df,
    feature_cols,
    edge_cols,
    max_neighbors=10,
    causal=True,
    edge_frame=None,
):
    """Build transaction nodes and same-entity edges.

    For causal graphs, edges point from earlier transactions to later ones. This
    lets a checkout aggregate historical context without allowing future
    transactions to influence an earlier prediction. `edge_cols` must contain
    the raw identifiers; model features may be independently transformed.
    """
    frame = df.reset_index(drop=True).copy()
    edges = (edge_frame if edge_frame is not None else frame).reset_index(drop=True)
    if len(edges) != len(frame):
        raise ValueError("Edge data and node features must have matching rows")
    if not feature_cols or any(column not in frame for column in feature_cols):
        raise ValueError("Graph feature columns are missing")
    if causal and "TransactionDT" in edges:
        ordering = np.argsort(edges["TransactionDT"].fillna(0).to_numpy(), kind="stable")
    elif "created_at" in edges:
        ordering = np.argsort(pd.to_datetime(edges["created_at"], errors="coerce").astype("int64").to_numpy(), kind="stable")
    else:
        ordering = np.arange(len(frame))
    rank = np.empty(len(frame), dtype=np.int64)
    rank[ordering] = np.arange(len(frame))

    sources, targets, edge_types = [], [], []
    for edge_type, column in enumerate(edge_cols):
        if column not in edges:
            continue
        normalized_keys = edges[column].astype(str).str.strip()
        valid = (
            edges[column].notna()
            & normalized_keys.ne("")
            & normalized_keys.str.casefold().ne("unknown")
        )
        groups = edges.loc[valid, [column]].assign(_node=np.flatnonzero(valid.to_numpy()))
        for _, rows in groups.groupby(column, sort=False, dropna=True):
            nodes = rows["_node"].to_numpy()
            nodes = nodes[np.argsort(rank[nodes], kind="stable")]
            if len(nodes) < 2:
                continue
            for position, target in enumerate(nodes):
                start = max(0, position - max_neighbors)
                predecessors = nodes[start:position]
                for source in predecessors:
                    sources.append(int(source))
                    targets.append(int(target))
                    edge_types.append(edge_type)
                    if not causal:
                        sources.append(int(target))
                        targets.append(int(source))
                        edge_types.append(edge_type)

    if sources:
        edge_index = torch.tensor([sources, targets], dtype=torch.long)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)

    x = torch.tensor(frame[feature_cols].to_numpy(dtype=np.float32, copy=True), dtype=torch.float32)
    y = torch.as_tensor(frame["isFraud"].to_numpy(dtype=np.float32), dtype=torch.float32) if "isFraud" in frame else None
    graph = Data(x=x, edge_index=edge_index, y=y)
    graph.edge_type = torch.tensor(edge_types, dtype=torch.long)
    if "TransactionID" in frame:
        graph.transaction_ids = frame["TransactionID"].to_numpy()
    return graph
