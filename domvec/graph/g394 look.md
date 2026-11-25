---
domvec: chat
---

## You

please provide simple code for a graph of friends

## Nous Hermes 2 Mistral DPO

Here is a small **networkx** sketch:

```python
import networkx as nx

graph = nx.Graph()
graph.add_edge('ana', 'bo')
print(graph.number_of_edges())
```

Add more edges the same way.
