# Tree Structure Facts — vertiscope 3D View

## Trie Data Structure (Python)

1. **Node linking** — vertiscope/trie.py:221: `children: Dict[str, "TrieNode"]` only. No back-parent pointer. Each node is keyed by a single segment string in exactly one parent's dict.

2. **No multiple parents** — By design, a child node appears as a value in only one parent's children dict. A node cannot be re-keyed in two parents' dicts simultaneously.

3. **Root definition** — vertiscope/trie.py:369: `self.root = TrieNode(segment="", depth=0)`. One root per Trie instance (one per page).

4. **Trie is acyclic by construction** — Parent-child traversal is downward only (`node.children.get(seg)`). No mechanism to create cycles.

## 3D View Edge Sources (TypeScript + Python)

5. **Parent-to-node edges (force)** — obsidian-plugin/src/graph.ts:734: `links.push({source: to, target: id, force: true})` where `to` is from `parentFor()` (lines 959–970). One force edge per node except page roots.

6. **parentFor fallback chain** — obsidian-plugin/src/graph.ts:959–970: tries stored parent → collapsed target → page node. Falls back to page node, never to multiple parents.

7. **Containment edges (non-force)** — vertiscope/obsidian/layout.py:1705–1706: two edge sources:
   - Parent-to-chunk edges: one per unfolded node
   - Containment edges from `contains_within(url)` (line 1497): chunk-to-chunk links where one contains the other

8. **Containment edges deduplicated** — vertiscope/obsidian/layout.py:1499–1502: self-edges dropped, duplicate edges dropped by `(source, target)` key.

9. **UNCONFIRMED — Containment and force edges can target the same node** — No code found that prevents a chunk from having both a force edge and a containment edge as parents. The layout layer and force layer operate independently.

## Tree Property Validation (Live Check)

10. **Multi-parent check exists** — obsidian-plugin/checks/live.mjs:1215: `C2_tree: tr.every((r) => r.multi_parent === 0)` asserts no node has >1 incoming force link.

11. **Multi-parent measured** — obsidian-plugin/checks/live.mjs:2021–2028: counts force-link targets per node; flags `multi_parent > 0` as tree violation.

12. **Page roots have no force parent** — obsidian-plugin/src/graph.ts:746–748: nodes with `!a.parent` and `pageNode` exist are stored with `parent: ""` (empty string), implying no force edge.

## Summary

The trie **is tree-structured**: one parent per node, no cycles. The 3D view's **force edges** are tree-structured per C2_tree check. However, **containment edges from layout are drawn separately** from force edges and can form a web. No code found preventing a node from being reached by both a force edge and a containment edge, making the full 3D graph a **DAG**, not a tree, if both are drawn.

---
*Facts 1–8, 10–12 confirmed via code citation. Fact 9 unconfirmed; needs review of how graph.ts/absorb merges containment edges with force edges.*
