"""
xpath_tree_builder.py — Build a collapsed content xpath tree from categorized xpaths.

Takes arrays of absolute xpaths (produced by ContentTagger) and constructs a
compressed JSON tree (Patricia trie / radix tree) where:
  - Content-free intermediate chains are collapsed into single path keys
  - Leaf and branch nodes carry _content metadata (category lists)
  - Array indices are preserved in path keys (e.g. /li[2])

The resulting JSON structure is persisted to KuzuDB and used for:
  1. 3D layout computation (tree structure → the UMAP-linear-radial LayoutService,
     §6.1; the forbidden Fibonacci-sphere distribution is NOT used)
  2. GUI rendering (each tree node → interactive 3D sphere)
  3. Label propagation (xpath patterns for commutation and LCA)
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# No shadow_html_parser dependency — this module works purely with xpath strings


# ---------------------------------------------------------------------------
# Trie construction
# ---------------------------------------------------------------------------

@dataclass
class _TrieNode:
    """Internal trie node during construction."""
    segment: str = ""
    children: Dict[str, '_TrieNode'] = field(default_factory=dict)
    content_categories: Set[str] = field(default_factory=set)
    is_content: bool = False
    xpath_count: int = 0  # how many original xpaths pass through here


def _split_xpath_segments(xpath: str) -> List[str]:
    """
    Split an absolute xpath into individual segments.

    '/html/body/div[2]/ul/li[3]/a' → ['html', 'body', 'div[2]', 'ul', 'li[3]', 'a']

    Handles shadow-root boundaries:
    '/html/body/div/#shadow-root/div' → ['html', 'body', 'div', '#shadow-root', 'div']
    """
    # Remove leading slash
    path = xpath.lstrip('/')
    if not path:
        return []
    return [s for s in path.split('/') if s]


def _segments_to_path_key(segments: List[str]) -> str:
    """Join segments back into a path key with leading slash."""
    return '/' + '/'.join(segments)


class XPathTreeBuilder:
    """
    Builds a collapsed content xpath tree from categorized xpath arrays.

    Usage:
        builder = XPathTreeBuilder()
        builder.add_xpaths(content_xpaths, category='urls')
        builder.add_xpaths(text_xpaths, category='text')
        tree = builder.build()
        # tree is a nested dict ready for JSON serialization
    """

    def __init__(self):
        self._root = _TrieNode(segment='')
        self._all_content_xpaths: Dict[str, Set[str]] = defaultdict(set)

    def add_xpaths(self, xpaths: List[str], category: str) -> None:
        """
        Insert a list of absolute xpaths into the trie, tagged with a category.

        Args:
            xpaths: List of absolute xpath strings
            category: Content category (e.g. 'urls', 'text', 'media', etc.)
        """
        for xpath in xpaths:
            self._all_content_xpaths[xpath].add(category)
            segments = _split_xpath_segments(xpath)
            self._insert(segments, category)

    def add_tagged_content(self, tagged) -> None:
        """
        Convenience: add all xpaths from a TaggedContent result.

        Args:
            tagged: A TaggedContent instance from ContentTagger
        """
        for group_name in ('urls', 'media', 'text', 'interactive', 'json_data'):
            group = getattr(tagged, group_name)
            for subcategory, xpaths in group.items():
                cat_label = f"{group_name}.{subcategory}"
                self.add_xpaths(xpaths, cat_label)

    def build(self) -> Dict[str, Any]:
        """
        Collapse the trie and return a JSON-serializable nested dict.

        Returns a tree where:
          - Keys are collapsed xpath path segments (e.g. '/body/div/div/li[0]')
          - Values are nested dicts for children
          - Leaf/branch content nodes have a '_content' key listing categories
          - '_xpath' stores the full absolute xpath for this node

        Example output:
        {
            "/html/body/div[1]": {
                "_xpath": "/html/body/div[1]",
                "/main/article": {
                    "_xpath": "/html/body/div[1]/main/article",
                    "/div[2]": {
                        "/h2": {"_content": ["text.visible"], "_xpath": "..."},
                        "/p[1]": {"_content": ["text.visible"], "_xpath": "..."}
                    }
                }
            }
        }
        """
        result = {}
        self._collapse_node(self._root, [], result)
        return resolve_tree_xpaths(result)

    def build_flat_nodes(self) -> List[Dict[str, Any]]:
        """
        Return a flat list of all content nodes with their full xpaths
        and categories. Useful for layout computation and GUI streaming.

        Returns list of:
            {'xpath': str, 'categories': [str], 'depth': int, 'parent_xpath': str}
        """
        tree = self.build()
        nodes = []
        self._flatten_tree(tree, nodes, parent_xpath='')
        return nodes

    # --- Internal methods ---

    def _insert(self, segments: List[str], category: str) -> None:
        """Insert a sequence of path segments into the trie."""
        node = self._root
        for seg in segments:
            node.xpath_count += 1
            if seg not in node.children:
                node.children[seg] = _TrieNode(segment=seg)
            node = node.children[seg]
        # Mark the terminal node
        node.is_content = True
        node.content_categories.add(category)
        node.xpath_count += 1

    def _collapse_node(self, node: _TrieNode, accumulated_segs: List[str],
                       output: Dict[str, Any]) -> None:
        """
        Recursively collapse single-child non-content chains into
        concatenated path keys.
        """
        for child_seg, child_node in node.children.items():
            chain = accumulated_segs + [child_seg]

            # Collapse: while this node has exactly one child and is NOT a
            # content node itself, merge it into the chain.
            #
            # A loop, not recursion. Following a chain used to cost one stack
            # frame per link, so a long enough single-child chain raised
            # `RecursionError` and lost the whole page. The wide sweep hit it
            # on five pages of 801; a plain tower of `<div>`s does it too,
            # measured fine at depth 600 and fatal by 1200, and deep wrapper
            # chains are ordinary in real markup.
            #
            # Chains are exactly the part that can be unbounded, and they are
            # also the part that needs no stack: the recursion below is over
            # genuine branch points, whose depth is bounded by how nested the
            # document really is.
            while (len(child_node.children) == 1
                    and not child_node.is_content):
                (only_seg, only_node), = child_node.children.items()
                chain.append(only_seg)
                child_node = only_node

            # A branch point or a content node: emit it.
            key = _segments_to_path_key(chain)
            full_xpath = key  # will be computed by walking from root

            subtree: Dict[str, Any] = {}

            # Attach content metadata if this is a content node
            if child_node.is_content:
                subtree['_content'] = sorted(child_node.content_categories)

            # Store the full xpath for this node
            subtree['_xpath'] = key

            # Recurse into children
            if child_node.children:
                self._collapse_node(child_node, [], subtree)

            output[key] = subtree

    def _flatten_tree(self, tree: Dict[str, Any], nodes: List[Dict],
                      parent_xpath: str, depth: int = 0) -> None:
        """Flatten the collapsed tree into a list of content nodes.

        Only nodes with actual content categories are emitted.
        Branch-only intermediate nodes are traversed for their
        descendants but do NOT appear in the flat output — this
        keeps the 3D GUI free of empty, contentless spheres.
        """
        for key, subtree in tree.items():
            if key.startswith('_'):
                continue  # skip metadata keys

            full_xpath = subtree.get('_xpath', key)
            categories = subtree.get('_content', [])

            if categories:
                nodes.append({
                    'xpath': full_xpath,
                    'categories': categories,
                    'depth': depth,
                    'parent_xpath': parent_xpath,
                    'is_branch': False,
                })

            # Recurse — use this node as parent only if it was emitted,
            # otherwise keep the previous parent so edges skip over
            # the invisible branch node.
            next_parent = full_xpath if categories else parent_xpath
            self._flatten_tree(subtree, nodes,
                               parent_xpath=next_parent,
                               depth=depth + 1)


# ---------------------------------------------------------------------------
# Utility: rebuild absolute xpaths in a collapsed tree
# ---------------------------------------------------------------------------

def resolve_tree_xpaths(tree: Dict[str, Any], prefix: str = '') -> Dict[str, Any]:
    """
    Walk a collapsed tree and replace all _xpath values with fully
    resolved absolute xpaths (concatenating parent prefixes).

    This is needed because collapsed keys like '/div[2]/h2' need to be
    prepended with their parent's full path.
    """
    resolved = {}
    for key, subtree in tree.items():
        if key.startswith('_'):
            resolved[key] = subtree
            continue

        full = prefix + key
        child = dict(subtree)
        child['_xpath'] = full

        # Recurse into non-metadata children
        child_resolved = {}
        for k, v in child.items():
            if isinstance(v, dict) and not k.startswith('_'):
                # This is a subtree child
                inner = resolve_tree_xpaths({k: v}, prefix=full)
                child_resolved.update(inner)
            else:
                child_resolved[k] = v

        resolved[key] = child_resolved

    return resolved


def count_content_nodes(tree: Dict[str, Any]) -> int:
    """Count total content nodes (nodes with _content key) in a tree."""
    count = 0
    for key, subtree in tree.items():
        if key.startswith('_'):
            continue
        if isinstance(subtree, dict):
            if '_content' in subtree:
                count += 1
            count += count_content_nodes(subtree)
    return count
