---
tags: [fixture]
---
A notebook about radix trees, with a cell before any heading.

```python {Radix tree}
import numpy as np
x = {"a": 1}
```
<!-- nb-output hash=abc count=1 status=ok -->
````text
{'a': 1}
````
<!-- /nb-output -->

# Building

Prose under building.

## Insert

```python {Radix tree} {keys}
from collections import defaultdict

class Node:
    """A trie node."""
    def child(self, k):
        """The child at k."""
        return self.kids[k]

def insert(root, key):
    return root
```

## Lookup #2

Look things up.

# Using

```bash
echo hi
```

Text after the cell.
