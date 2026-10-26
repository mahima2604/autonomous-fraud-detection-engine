import torch
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv

class GraphSAGE(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels=1, num_layers=2, dropout=0.5,
                 categorical_cardinalities=None, embedding_dim=16):
        super(GraphSAGE, self).__init__()

        self.categorical_cardinalities = categorical_cardinalities or []
        self.embeddings = torch.nn.ModuleList(
            [torch.nn.Embedding(size, embedding_dim) for size in self.categorical_cardinalities]
        )
        if self.embeddings:
            self.input_projection = torch.nn.Linear(1 + len(self.embeddings) * embedding_dim, hidden_channels)
        else:
            self.input_projection = torch.nn.Identity()
        
        self.convs = torch.nn.ModuleList()
        conv_input = hidden_channels if self.embeddings else in_channels
        self.convs.append(SAGEConv(conv_input, hidden_channels))
        
        for _ in range(num_layers - 2):
            self.convs.append(SAGEConv(hidden_channels, hidden_channels))
            
        if num_layers > 1:
            self.convs.append(SAGEConv(hidden_channels, hidden_channels))
            
        # Final classification layer
        self.classifier = torch.nn.Linear(hidden_channels, out_channels)
        self.dropout = dropout

    def forward(self, x, edge_index):
        if self.embeddings:
            embedded = [embedding(x[:, index + 1].long().clamp(0, embedding.num_embeddings - 1))
                        for index, embedding in enumerate(self.embeddings)]
            x = self.input_projection(torch.cat([x[:, :1], *embedded], dim=1))
            x = F.relu(x)
        for i, conv in enumerate(self.convs):
            x = conv(x, edge_index)
            if i < len(self.convs) - 1:
                x = F.relu(x)
                x = F.dropout(x, p=self.dropout, training=self.training)
                
        # For binary classification, output a single logit and use BCEWithLogitsLoss
        logits = self.classifier(x)
        # Keep a stable one-dimensional output even for a one-node inference graph.
        return logits.reshape(-1)
