import numpy as np
import pandas as pd
import pytest
import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.model import GraphSAGE
from app.models.fraud_prediction import FraudPrediction
from app.models.user import User
from app.database.session import Base


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gnn.sqlite'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_graph_edges_only_use_earlier_matching_transactions():
    nodes = pd.DataFrame({"TransactionAmt": [0.1, 0.2, 0.3]})
    edges = pd.DataFrame({
        "P_emaildomain": ["shared.example", "shared.example", "shared.example"],
        "TransactionDT": [10, 20, 30],
    })
    graph = build_homogeneous_transaction_graph(
        nodes, ["TransactionAmt"], ["P_emaildomain"], edge_frame=edges,
    )
    pairs = set(map(tuple, graph.edge_index.t().tolist()))
    assert pairs == {(0, 1), (0, 2), (1, 2)}
    assert graph.x.shape == (3, 1)


def test_graphsage_returns_one_logit_per_node_including_single_node():
    model = GraphSAGE(in_channels=5, hidden_channels=8, num_layers=2)
    logits = model(torch.zeros((1, 5)), torch.empty((2, 0), dtype=torch.long))
    assert logits.shape == (1,)


def test_trained_artifact_loads_and_scores_live_checkout(database):
    assert main.gnn_artifacts_loaded
    assert main.gnn_metadata["in_channels"] == 5
    assert main.gnn_model is not None
    user = User(name="Test", email="gnn@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=42.5,
            ProductCD="UNKNOWN",
            P_emaildomain="example.test",
            DeviceType="desktop",
            DeviceInfo="test-device",
        ),
        db=database,
        current_user=user,
    )
    assert response.model_used == "GraphSAGE"
    assert np.isfinite(response.fraud_probability)
    assert 0 <= response.fraud_probability <= 1
    assert database.query(FraudPrediction).one().model_used == "GraphSAGE"
