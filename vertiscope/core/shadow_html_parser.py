"""
Shadow DOM HTML Parser

A shadow-DOM-aware HTML parser that creates a soup-like object capable of
xpath searches through shadow DOM nodes with tag-agnostic parent, child,
and attribute access.
"""

from __future__ import annotations
import re
from html.parser import HTMLParser
from typing import Optional, Iterator, Any
from dataclasses import dataclass, field
from collections import deque


# Void elements (self-closing, no end tag)
VOID_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
})


@dataclass
class ShadowNode:
    """
    Represents a node in the shadow-aware DOM tree.
    Provides tag-agnostic access to parent, children, and attributes.
    """
    tag: str
    attributes: dict = field(default_factory=dict)
    parent: Optional['ShadowNode'] = field(default=None, repr=False)
    children: list['ShadowNode'] = field(default_factory=list)
    text: str = ""
    tail: str = ""
    shadow_root: Optional['ShadowNode'] = field(default=None)
    is_shadow_root: bool = False
    _source_line: int = 0
    _source_col: int = 0

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    # --- Attribute access ---
    def get_attr(self, name: str, default: Any = None) -> Any:
        return self.attributes.get(name, default)

    def set_attr(self, name: str, value: Any) -> None:
        self.attributes[name] = value

    def has_attr(self, name: str) -> bool:
        return name in self.attributes

    def get_all_attrs(self) -> dict:
        return dict(self.attributes)

    # --- Parent access ---
    def get_parent(self) -> Optional['ShadowNode']:
        return self.parent

    def get_ancestors(self) -> Iterator['ShadowNode']:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    # --- Child access ---
    def get_children(self, include_shadow: bool = True) -> list['ShadowNode']:
        """Return light DOM children, optionally flattening shadow root children in."""
        if include_shadow and self.shadow_root and self.shadow_root.children:
            if not hasattr(self, '_cached_shadow_children'):
                self._cached_shadow_children = self.children + self.shadow_root.children
            return self._cached_shadow_children
        return self.children

    def get_children_with_shadow_boundary(self) -> list['ShadowNode']:
        """Return children INCLUDING the shadow root node itself as a child.
        This is used by the XPath evaluator to traverse #shadow-root steps."""
        result = list(self.children)
        if self.shadow_root:
            result.append(self.shadow_root)
        return result

    def get_child(self, index: int) -> Optional['ShadowNode']:
        children = self.get_children()
        if 0 <= index < len(children):
            return children[index]
        return None

    def get_first_child(self) -> Optional['ShadowNode']:
        return self.get_child(0)

    def get_last_child(self) -> Optional['ShadowNode']:
        children = self.get_children()
        return children[-1] if children else None

    # --- Sibling access ---
    def get_siblings(self) -> list['ShadowNode']:
        if not self.parent:
            return []
        return [c for c in self.parent.get_children() if c is not self]

    def get_next_sibling(self) -> Optional['ShadowNode']:
        if not self.parent:
            return None
        children = self.parent.get_children()
        for i, child in enumerate(children):
            if child is self and i + 1 < len(children):
                return children[i + 1]
        return None

    def get_prev_sibling(self) -> Optional['ShadowNode']:
        if not self.parent:
            return None
        children = self.parent.get_children()
        for i, child in enumerate(children):
            if child is self and i > 0:
                return children[i - 1]
        return None

    # --- Traversal ---
    def iter_descendants(self, include_shadow: bool = True) -> Iterator['ShadowNode']:
        """Iterative BFS traversal of all descendants."""
        queue = deque(self.get_children(include_shadow))
        while queue:
            node = queue.popleft()
            yield node
            queue.extend(node.get_children(include_shadow))

    def iter_all(self, include_shadow: bool = True) -> Iterator['ShadowNode']:
        """Yield self plus all descendants."""
        yield self
        yield from self.iter_descendants(include_shadow)

    # --- Text ---
    # Attributes whose values are human-readable text (not URLs/IDs).
    _TEXT_ATTRS = ('alt', 'aria-label', 'aria-describedby', 'title',
                   'placeholder', 'aria-roledescription')

    def get_text(self, recursive: bool = True, separator: str = "") -> str:
        if not recursive:
            return self.text or ""
        parts = []
        for node in self.iter_all():
            if node.text:
                parts.append(node.text)
            # Extract text from semantic attributes on elements that
            # carry no visible text children (img, input, svg, etc.).
            if not node.text and not any(True for _ in node.get_children()):
                for attr_name in self._TEXT_ATTRS:
                    val = node.get_attr(attr_name, '').strip()
                    if val and len(val) > 1:
                        parts.append(val)
                        break  # one attribute text per node
            if node.tail:
                parts.append(node.tail)
        if separator:
            return separator.join(parts)
        # Smart word-boundary injection: when two adjacent text
        # fragments would concatenate alphanumeric characters with
        # no whitespace between, insert a space.  This handles the
        # BFS-order issue where sibling elements at different depths
        # (e.g. <span>32</span><span>Tarot</span>) run together.
        result = []
        for part in parts:
            if result and part:
                prev = result[-1]
                if (prev and prev[-1].isalnum() and part[0].isalnum()):
                    result.append(' ')
            result.append(part)
            
        final_text = ''.join(result)
        if not separator:
            self._cached_get_text = final_text
        return final_text

    # --- Find ---
    def find(self, tag: Optional[str] = None, **attrs) -> Optional['ShadowNode']:
        for node in self.find_all(tag, **attrs):
            return node
        return None

    def find_all(self, tag: Optional[str] = None, **attrs) -> list['ShadowNode']:
        results = []
        for node in self.iter_descendants(include_shadow=True):
            if tag and node.tag.lower() != tag.lower():
                continue
            if attrs:
                match = True
                for attr_name, attr_value in attrs.items():
                    if attr_name == 'class_':
                        attr_name = 'class'
                    node_val = node.get_attr(attr_name)
                    if attr_value is True:
                        if not node.has_attr(attr_name):
                            match = False
                            break
                    elif node_val != attr_value:
                        match = False
                        break
                if not match:
                    continue
            results.append(node)
        return results

    # --- XPath on node ---
    def xpath(self, expression: str) -> list['ShadowNode']:
        """Execute XPath relative to this node."""
        evaluator = XPathEvaluator(self)
        return evaluator.select(expression, self)

    # --- Repr ---
    def __repr__(self):
        attrs_str = " ".join(f'{k}="{v}"' for k, v in list(self.attributes.items())[:3])
        if attrs_str:
            return f"<ShadowNode tag='{self.tag}' {attrs_str}>"
        return f"<ShadowNode tag='{self.tag}'>"

    def to_html(self, indent: int = 0) -> str:
        prefix = "  " * indent
        tag = self.tag
        if tag.startswith('#'):
            return ""
        attrs = " ".join(f'{k}="{v}"' for k, v in self.attributes.items())
        opening = f"<{tag} {attrs}>" if attrs else f"<{tag}>"

        children_html = []
        for child in self.get_children():
            child_html = child.to_html(indent + 1)
            if child_html:
                children_html.append(child_html)
            # Append tail text (text after this child, belonging to parent)
            tail = child.tail.strip() if child.tail else ""
            if tail:
                children_html.append(f"{'  ' * (indent + 1)}{tail}")

        text_part = self.text.strip() if self.text else ""

        if not children_html and not text_part:
            return f"{prefix}{opening}</{tag}>"

        parts = [f"{prefix}{opening}"]
        if text_part:
            parts.append(f"{'  ' * (indent + 1)}{text_part}")
        parts.extend(children_html)
        parts.append(f"{prefix}</{tag}>")
        return "\n".join(parts)


# =============================================================================
# XPATH EVALUATOR
# =============================================================================

class XPathEvaluator:
    """Evaluates XPath expressions against a ShadowNode tree,
    with full support for #shadow-root boundary traversal."""

    def __init__(self, root: ShadowNode):
        self.root = root

    def select(self, xpath: str, context: Optional[ShadowNode] = None) -> list[ShadowNode]:
        if context is None:
            context = self.root
        return self._execute_xpath(xpath.strip(), context)

    def select_one(self, xpath: str, context: Optional[ShadowNode] = None) -> Optional[ShadowNode]:
        results = self.select(xpath, context)
        return results[0] if results else None

    def _execute_xpath(self, xpath: str, context: ShadowNode) -> list[ShadowNode]:
        if xpath.startswith("//"):
            return self._select_descendants(xpath[2:], context)
        elif xpath.startswith("/"):
            return self._select_path(xpath[1:], self.root)
        elif xpath.startswith(".//"):
            return self._select_descendants(xpath[3:], context)
        elif xpath.startswith("./"):
            return self._select_path(xpath[2:], context)
        elif xpath.startswith(".."):
            if context.parent:
                if xpath == "..":
                    return [context.parent]
                return self._execute_xpath(xpath[3:], context.parent)
            return []
        else:
            return self._select_path(xpath, context)

    def _get_step_children(self, node: ShadowNode, tag: str) -> list[ShadowNode]:
        """Get children of node for a given step, handling #shadow-root specially."""
        if tag == '#shadow-root':
            # Return the shadow root node itself if present
            if node.shadow_root:
                return [node.shadow_root]
            return []
        # For normal tags, search both light DOM children AND shadow root's children
        # (but NOT the shadow root node itself — it's only reachable via #shadow-root step)
        return node.get_children(include_shadow=True)

    def _get_desc_candidates(self, node: ShadowNode, tag: str) -> Iterator[ShadowNode]:
        """Get descendant candidates, yielding shadow root nodes when needed."""
        queue = deque()
        # Seed: include shadow root node + light DOM children
        if node.shadow_root:
            queue.append(node.shadow_root)
        queue.extend(node.children)
        while queue:
            child = queue.popleft()
            yield child
            if child.shadow_root:
                queue.append(child.shadow_root)
            queue.extend(child.children)

    def _select_descendants(self, step: str, node: ShadowNode) -> list[ShadowNode]:
        results = []
        step_expr, remaining = self._parse_step(step)
        tag, predicates = self._parse_step_expr(step_expr)

        for desc in self._get_desc_candidates(node, tag):
            if self._matches_step(desc, tag, predicates):
                if remaining:
                    if remaining.startswith("//"):
                        results.extend(self._select_descendants(remaining[2:], desc))
                    elif remaining.startswith("/"):
                        results.extend(self._select_path(remaining[1:], desc))
                else:
                    results.append(desc)
        return results

    def _select_path(self, path: str, context: ShadowNode) -> list[ShadowNode]:
        if not path:
            return [context]

        step_expr, remaining = self._parse_step(path)
        tag, predicates = self._parse_step_expr(step_expr)

        # Get children appropriate for this step type
        children = self._get_step_children(context, tag)

        matches = []
        for child in children:
            if self._matches_step(child, tag, predicates):
                matches.append(child)

        if not remaining:
            return matches

        results = []
        for match in matches:
            if remaining.startswith("//"):
                results.extend(self._select_descendants(remaining[2:], match))
            elif remaining.startswith("/"):
                results.extend(self._select_path(remaining[1:], match))
        return results

    def _parse_step(self, path: str) -> tuple[str, str]:
        """Split path into first step and remaining path."""
        depth = 0
        for i, ch in enumerate(path):
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
            elif ch == '/' and depth == 0 and i > 0:
                return path[:i], path[i:]
        return path, ""

    def _parse_step_expr(self, step: str) -> tuple[str, list[str]]:
        """Parse step into tag name and predicates."""
        if '[' not in step:
            return step, []
        tag = step[:step.index('[')]
        predicates = []
        depth = 0
        start = None
        for i, ch in enumerate(step):
            if ch == '[' and depth == 0:
                start = i + 1
                depth = 1
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0 and start is not None:
                    predicates.append(step[start:i])
                    start = None
        return tag, predicates

    def _matches_step(self, node: ShadowNode, tag: str, predicates: list[str]) -> bool:
        if tag != '*' and node.tag.lower() != tag.lower():
            return False
        for pred in predicates:
            if not self._evaluate_predicate(node, pred):
                return False
        return True

    def _evaluate_predicate(self, node: ShadowNode, predicate: str) -> bool:
        predicate = predicate.strip()

        # Handle 'and' compound
        if ' and ' in predicate:
            parts = predicate.split(' and ')
            return all(self._evaluate_predicate(node, p.strip()) for p in parts)

        # Handle 'or' compound
        if ' or ' in predicate:
            parts = predicate.split(' or ')
            return any(self._evaluate_predicate(node, p.strip()) for p in parts)

        # Positional: [N]
        if predicate.isdigit():
            idx = int(predicate)
            if node.parent:
                same_tag = [c for c in node.parent.get_children() if c.tag == node.tag]
                return same_tag.index(node) + 1 == idx if node in same_tag else False
            return idx == 1

        # contains(@attr, 'value')
        contains_match = re.match(r"contains\(@(\w[\w\-]*),\s*'([^']*)'\)", predicate)
        if contains_match:
            attr_name = contains_match.group(1)
            search_val = contains_match.group(2)
            attr_val = str(node.get_attr(attr_name, ''))
            return search_val in attr_val

        # starts-with(@attr, 'value')
        starts_match = re.match(r"starts-with\(@(\w[\w\-]*),\s*'([^']*)'\)", predicate)
        if starts_match:
            attr_name = starts_match.group(1)
            search_val = starts_match.group(2)
            attr_val = str(node.get_attr(attr_name, ''))
            return attr_val.startswith(search_val)

        # @attr='value'
        eq_match = re.match(r"@(\w[\w\-]*)\s*=\s*'([^']*)'", predicate)
        if eq_match:
            attr_name = eq_match.group(1)
            attr_val = eq_match.group(2)
            return str(node.get_attr(attr_name, '')) == attr_val

        # @attr (existence check)
        attr_match = re.match(r"@(\w[\w\-]*)", predicate)
        if attr_match:
            return node.has_attr(attr_match.group(1))

        # not(...)
        not_match = re.match(r"not\((.+)\)", predicate)
        if not_match:
            return not self._evaluate_predicate(node, not_match.group(1))

        return False


# =============================================================================
# SHADOW DOM PARSER
# =============================================================================

class ShadowDOMParser(HTMLParser):
    """
    Parses HTML with shadow DOM support (via <template shadowrootmode>).
    """

    SHADOW_ATTRS = ('shadowrootmode', 'shadowroot')

    def __init__(self):
        super().__init__()
        self.root = ShadowNode(tag='#document')
        self.current = self.root
        self._in_shadow_template = False
        self._shadow_host = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_dict = {}
        for name, value in attrs:
            attr_dict[name.lower()] = value if value is not None else ""

        node = ShadowNode(
            tag=tag,
            attributes=attr_dict,
            parent=self.current,
            _source_line=self.getpos()[0],
            _source_col=self.getpos()[1],
        )
        self.current.children.append(node)

        # Check for shadow root template
        if tag == 'template' and any(
            attr_dict.get(sa) for sa in self.SHADOW_ATTRS
        ):
            shadow_root = ShadowNode(
                tag='#shadow-root',
                parent=self.current,
                is_shadow_root=True,
            )
            self.current.shadow_root = shadow_root
            self._in_shadow_template = True
            self._shadow_host = self.current
            self.current = shadow_root
            return

        if tag in VOID_ELEMENTS:
            return  # Don't push onto stack

        self.current = node

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in VOID_ELEMENTS:
            return

        if tag == 'template' and self._in_shadow_template:
            self._in_shadow_template = False
            self.current = self._shadow_host
            self._shadow_host = None
            return

        # Walk up to find matching open tag
        node = self.current
        while node and node is not self.root:
            if node.tag == tag:
                self.current = node.parent if node.parent else self.root
                return
            node = node.parent

        # If no match found, just leave current as is
        pass

    def handle_data(self, data):
        stripped = data.strip()
        if not stripped:
            return

        if self.current.children:
            # Text after child elements -> tail of last child
            last_child = self.current.children[-1]
            if last_child.tail:
                last_child.tail += " " + stripped
            else:
                last_child.tail = stripped
        else:
            if self.current.text:
                self.current.text += " " + stripped
            else:
                self.current.text = stripped

    def handle_comment(self, data):
        pass  # Skip comments

    def handle_decl(self, decl):
        pass  # Skip declarations


# =============================================================================
# SHADOW DOM
# =============================================================================

class ShadowDOM:
    """
    Shadow-DOM-aware document object model.
    Provides xpath search, iteration, and structural access.
    """

    def __init__(self, html: str):
        parser = ShadowDOMParser()
        parser.feed(html)
        self.root = parser.root
        self._xpath_eval = XPathEvaluator(self.root)
        # Kept for the one consumer that needs the bytes rather than the tree:
        # a `text/plain` document, where `html.parser` has already eaten any
        # angle-bracketed prose as a tag. `<Douglas Crockford>` in an RFC is
        # not markup, and by the time it reaches the tree it is gone.
        self.source = html

    @classmethod
    def from_file(cls, filepath: str) -> 'ShadowDOM':
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return cls(f.read())

    @classmethod
    def from_json_tree(cls, tree: dict) -> 'ShadowDOM':
        """Build a ShadowDOM directly from the scanner's JSON tree.

        Skips the ``serialize_to_html`` → ``HTMLParser`` round-trip that
        the ``__init__(html)`` path goes through. Both passes are
        O(|tree|) string operations on the entire master tree, repeated
        on every distill iteration; for a 100K-node page they
        contribute ~30% of the per-iter wall time.

        The JSON tree (produced by ``EXTRACT_DOM_JSON_JS`` in
        ``scanner.py``) already carries every structural fact we need:
        ``tagName`` / ``attributes`` / ``children`` / ``textContent`` /
        ``shadowRoot``. We walk it once and produce the same
        ``ShadowNode`` forest that the HTML parser would produce,
        matching its text/tail semantics so downstream consumers
        (``ContentTagger``, ``XPathTreeBuilder``, ``ChunkBuilder``) see
        an identical input shape.

        Differences from the HTML round-trip:
        * The serialized HTML wraps each shadow root in a ghost
          ``<template shadowrootmode>`` element that re-parses into a
          duplicate child of the host. This walker skips that ghost —
          it's never read by downstream code (everything that needs
          the shadow tree uses ``node.shadow_root`` directly), and
          eliminating it actually produces a *cleaner* tree.
        * Comments, doctype, and ``nodeType==3`` text nodes that
          contain only whitespace are dropped exactly as the parser
          drops them (whitespace text was already filtered by the JS
          extractor; we re-check defensively).
        """
        instance = cls.__new__(cls)
        root = ShadowNode(tag='#document')

        def _walk(json_children, parent):
            for obj in json_children:
                if not obj:
                    continue
                node_type = obj.get('nodeType', 1)
                if node_type == 3:
                    txt = (obj.get('textContent') or '').strip()
                    if not txt:
                        continue
                    # HTML parser semantics: text BEFORE any element
                    # child is parent.text; text AFTER becomes the
                    # tail of the previous element child.
                    if parent.children:
                        last = parent.children[-1]
                        last.tail = (last.tail + ' ' + txt) if last.tail else txt
                    else:
                        parent.text = (parent.text + ' ' + txt) if parent.text else txt
                    continue
                if node_type != 1:
                    # doctype / comment / unknown — match the HTML
                    # parser which drops these silently.
                    continue
                tag = (obj.get('tagName') or obj.get('nodeName') or '').lower()
                if not tag or tag.startswith('#'):
                    continue
                attrs = dict(obj.get('attributes') or {})
                # The JS extractor sometimes promotes id / className to
                # top-level fields for convenience. Mirror them back into
                # the attributes map so xpath predicates work.
                if obj.get('id') and 'id' not in attrs:
                    attrs['id'] = obj['id']
                if obj.get('className') and 'class' not in attrs:
                    attrs['class'] = obj['className']
                node = ShadowNode(tag=tag, attributes=attrs, parent=parent)
                parent.children.append(node)

                shadow = obj.get('shadowRoot')
                if shadow:
                    # The shadow root's parent is the HOST element so
                    # ``get_absolute_xpath`` produces ``host/#shadow-root/...``
                    # rather than skipping the host. Mirrors the
                    # HTMLParser path which had ``self.current == host``
                    # at the moment the shadow root was created.
                    shadow_node = ShadowNode(
                        tag='#shadow-root',
                        parent=node,
                        is_shadow_root=True,
                    )
                    node.shadow_root = shadow_node
                    _walk(shadow.get('children') or [], shadow_node)

                grand = obj.get('children') or []
                if grand:
                    _walk(grand, node)

        if tree:
            _walk([tree], root)

        instance.root = root
        instance._xpath_eval = XPathEvaluator(root)
        return instance

    def xpath(self, expression: str) -> list[ShadowNode]:
        return self._xpath_eval.select(expression)

    def xpath_one(self, expression: str) -> Optional[ShadowNode]:
        results = self.xpath(expression)
        return results[0] if results else None

    def iter_all(self) -> Iterator[ShadowNode]:
        return self.root.iter_all(include_shadow=True)

    def iter_elements(self) -> Iterator[ShadowNode]:
        for node in self.root.iter_all(include_shadow=True):
            if not node.tag.startswith('#'):
                yield node

    def __iter__(self) -> Iterator[ShadowNode]:
        return self.iter_all()

    def __repr__(self):
        count = sum(1 for _ in self.iter_elements())
        return f"<ShadowDOM elements={count}>"


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_absolute_xpath(node: ShadowNode) -> str:
    """Generate absolute XPath for a node, including shadow boundaries."""
    if hasattr(node, '_cached_absolute_xpath'):
        return node._cached_absolute_xpath

    path_nodes = []
    current = node

    while current and current.parent:
        if hasattr(current, '_cached_absolute_xpath'):
            break
        path_nodes.append(current)
        current = current.parent
        
    path_nodes.reverse()
    
    base_path = ""
    if current:
        if hasattr(current, '_cached_absolute_xpath'):
            base_path = current._cached_absolute_xpath
        else:
            base_path = "/"
            current._cached_absolute_xpath = base_path
            
    if base_path == "/":
        base_path = ""

    for n in path_nodes:
        if n.is_shadow_root:
            segment = "#shadow-root"
        elif n.tag.startswith('#'):
            segment = ""
        else:
            parent = n.parent
            
            # O(1) Sibling Index Caching Optimization
            if not hasattr(parent, '_tag_counts'):
                counts = {}
                for c in parent.children:
                    t = c.tag
                    counts[t] = counts.get(t, 0) + 1
                parent._tag_counts = counts
                
            if parent._tag_counts.get(n.tag, 0) > 1:
                if not hasattr(n, '_xpath_index'):
                    idx = 1
                    for c in parent.children:
                        if c.tag == n.tag:
                            c._xpath_index = idx
                            idx += 1
                segment = f"{n.tag}[{n._xpath_index}]"
            else:
                segment = n.tag
                
        base_path = f"{base_path}/{segment}" if segment else (base_path or "/")
        n._cached_absolute_xpath = base_path
        
    return node._cached_absolute_xpath


def get_relative_xpath(node: ShadowNode, ancestor: ShadowNode) -> str:
    """Generate relative XPath from ancestor to node."""
    parts = []
    current = node

    while current and current is not ancestor and current.parent:
        if current.is_shadow_root:
            parts.append("#shadow-root")
        elif not current.tag.startswith('#'):
            parent = current.parent
            
            # O(1) Sibling Index Caching Optimization
            if not hasattr(parent, '_tag_counts'):
                counts = {}
                for c in parent.children:
                    t = c.tag
                    counts[t] = counts.get(t, 0) + 1
                parent._tag_counts = counts
                
            if parent._tag_counts.get(current.tag, 0) > 1:
                if not hasattr(current, '_xpath_index'):
                    idx = 1
                    for c in parent.children:
                        if c.tag == current.tag:
                            c._xpath_index = idx
                            idx += 1
                parts.append(f"{current.tag}[{current._xpath_index}]")
            else:
                parts.append(current.tag)
        current = current.parent

    parts.reverse()
    return "./" + "/".join(parts) if parts else "."