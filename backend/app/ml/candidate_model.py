"""Candidate Graph Neural Network architecture for storefront checkout fraud assessment."""

import torch
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv


class CandidateGraphSAGE(torch.nn.Module):
    """GraphSAGE model for storefront transactions with multi-field numerical and categorical features."""

    def __init__(
        self,
        numerical_dim: int,
        categorical_cardinalities: list[int],
        hidden_channels: int = 64,
        out_channels: int = 1,
        num_layers: int = 2,
        dropout: float = 0.5,
        embedding_dim: int = 16,
    ):
        super().__init__()
        self.numerical_dim = numerical_dim
        self.categorical_cardinalities = categorical_cardinalities or []
        self.embedding_dim = embedding_dim
        self.dropout = dropout

        # Categorical embedding tables
        self.embeddings = torch.nn.ModuleList([
            torch.nn.Embedding(cardinality, embedding_dim)
            for cardinality in self.categorical_cardinalities
        ])

        # Dense projection combining numerical inputs and all categorical embeddings
        combined_dim = self.numerical_dim + len(self.embeddings) * embedding_dim
        self.input_projection = torch.nn.Linear(combined_dim, hidden_channels)

        # Graph convolution layers
        self.convs = torch.nn.ModuleList()
        self.convs.append(SAGEConv(hidden_channels, hidden_channels))
        for _ in range(num_layers - 2):
            self.convs.append(SAGEConv(hidden_channels, hidden_channels))
        if num_layers > 1:
            self.convs.append(SAGEConv(hidden_channels, hidden_channels))

        # Binary classification head
        self.classifier = torch.nn.Linear(hidden_channels, out_channels)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        """Forward pass over node features and edge indices.

        Args:
            x: Tensor of shape (num_nodes, numerical_dim + num_categorical)
               where x[:, :numerical_dim] are continuous scaled floats, and
               x[:, numerical_dim:] are encoded integer categorical indices.
            edge_index: Graph edge tensor of shape (2, num_edges).

        Returns:
            Logits of shape (num_nodes,).
        """
        x_num = x[:, :self.numerical_dim]

        if self.embeddings:
            embedded_features = []
            for idx, embedding in enumerate(self.embeddings):
                cat_indices = x[:, self.numerical_dim + idx].long().clamp(0, embedding.num_embeddings - 1)
                embedded_features.append(embedding(cat_indices))
            x_combined = torch.cat([x_num, *embedded_features], dim=1)
        else:
            x_combined = x_num

        h = F.relu(self.input_projection(x_combined))

        for i, conv in enumerate(self.convs):
            h = conv(h, edge_index)
            if i < len(self.convs) - 1:
                h = F.relu(h)
                h = F.dropout(h, p=self.dropout, training=self.training)

        logits = self.classifier(h)
        return logits.reshape(-1)
