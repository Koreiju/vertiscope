"""
chunk_query.py — Extraction query execution.

Queries a :class:`ShadowDOM` with a chunk pattern and its
``extraction_trie`` (the per-instance data-address schema produced by
``ChunkBuilder``), producing one :class:`InstanceResult` per DOM match.

Contract
--------
* ``query_chunk`` yields **only** instances whose extraction produced at
  least one populated field. Empty-dict instances used to slip through
  and surface as "Instance 13:" blanks in the demo — they're dropped
  here because an instance with no resolved data is neither renderable
  nor embeddable.
* Every ``InstanceResult`` carries the instance's absolute xpath so
  downstream consumers (render, embed, retrieval) can address each
  instance back to the DOM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from vertiscope.core.shadow_html_parser import ShadowDOM, ShadowNode, get_absolute_xpath
from vertiscope.core.xpath_utils import generalize_xpath


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class InstanceResult:
    """One populated instance of a chunk pattern.

    Attributes
    ----------
    absolute_xpath:
        The concrete xpath of this instance's root node (e.g.
        ``/html/body/main/section/article[2]``). Together with
        :attr:`fields` this is what lets the render / embed / retrieval
        layers address each instance independently.
    fields:
        ``{relative_extended_generalized_xpath: [values]}``. Mirrors the
        previous flat-dict return shape so existing ``inst.fields.items()``
        iteration keeps working.
    """

    absolute_xpath: str
    fields: Dict[str, List[Any]] = field(default_factory=dict)

    # -- ergonomic dict-like accessors --------------------------------

    def items(self) -> Iterator:
        return self.fields.items()

    def keys(self) -> Iterator:
        return self.fields.keys()

    def values(self) -> Iterator:
        return self.fields.values()

    def __iter__(self) -> Iterator[str]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __getitem__(self, key: str) -> List[Any]:
        return self.fields[key]

    def __contains__(self, key: str) -> bool:
        return key in self.fields

    def __bool__(self) -> bool:
        # ``assert inst`` checks "has at least one resolved field" —
        # empty-dict instances are already filtered out of ``query_chunk``
        # but this keeps the truthiness semantics a caller would expect.
        return bool(self.fields)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def is_empty(self) -> bool:
        return not self.fields


# ---------------------------------------------------------------------------
# Core query
# ---------------------------------------------------------------------------


def query_chunk(
    dom: ShadowDOM,
    chunk_pattern: str,
    extraction_trie: Dict[str, Any],
) -> List[InstanceResult]:
    """Find every subtree in ``dom`` matching ``chunk_pattern`` and
    extract its fields via ``extraction_trie``.

    Returns
    -------
    list[InstanceResult]
        Populated instances only. Empty results (where no field key
        resolved against the subtree) are silently dropped and their
        count is logged at DEBUG.
    """
    # Pre-compute generalized xpath for every DOM node; reused both for
    # the chunk-pattern match and for matching extraction-trie leaves
    # against descendants.
    node_to_gen_xpath: Dict[int, str] = {}
    matching_nodes: List[ShadowNode] = []
    for node in dom.iter_all():
        abs_xp = get_absolute_xpath(node)
        if not abs_xp:
            continue
        gen_xp = generalize_xpath(abs_xp)
        node_to_gen_xpath[id(node)] = gen_xp
        if gen_xp == chunk_pattern:
            matching_nodes.append(node)

    results: List[InstanceResult] = []
    skipped_empty = 0
    for node in matching_nodes:
        base_gen_xp = node_to_gen_xpath[id(node)]
        extracted: Dict[str, List[Any]] = {}
        _evaluate_trie(
            node, extraction_trie, "", base_gen_xp,
            node_to_gen_xpath, extracted,
        )
        if not extracted:
            skipped_empty += 1
            continue
        abs_xp = get_absolute_xpath(node)
        results.append(InstanceResult(absolute_xpath=abs_xp, fields=extracted))

    if skipped_empty:
        logger.debug(
            "query_chunk: dropped %d empty instance(s) of pattern %r "
            "(structural match but no tagged content resolved).",
            skipped_empty, chunk_pattern,
        )

    return results


def _evaluate_trie(
    base_node: ShadowNode,
    trie: Dict[str, Any],
    current_rel_path: str,
    base_gen_xp: str,
    node_to_gen_xpath: Dict[int, str],
    results: Dict[str, List[Any]],
    gen_xp_to_descendants: Optional[Dict[str, List[ShadowNode]]] = None,
) -> None:
    """Recursively evaluate the trie using descendants of ``base_node``.

    Populates ``results`` in place, keyed by the extended-generalized
    relative path (``/a/h3/text()``, ``/a/@href`` …).

    ``gen_xp_to_descendants`` is a ``gen_xp → [descendants]`` bucket scoped
    to ``base_node``. Built once at the top of the outermost call and
    threaded through recursion so each data-address leaf becomes an O(1)
    dict lookup instead of a full ``iter_all`` re-walk. On pages with many
    chunks this removes a per-leaf O(subtree) scan that dominated render.
    """
    if gen_xp_to_descendants is None:
        gen_xp_to_descendants = {}
        for descendant in base_node.iter_all():
            gx = node_to_gen_xpath.get(id(descendant))
            if gx is None:
                continue
            gen_xp_to_descendants.setdefault(gx, []).append(descendant)

    root_tag = base_gen_xp.rstrip("/").split("/")[-1].split("[")[0] if base_gen_xp != "/" else "root"
    prefix = f"/{root_tag}"

    for key, subtree in trie.items():
        if key.startswith("@") or key == "text()":
            # Data-address leaf — resolve now.
            full_route = (
                current_rel_path + f"/{key}" if current_rel_path else f"/{key}"
            )

            actual_rel = current_rel_path[len(prefix):] if current_rel_path.startswith(prefix) else current_rel_path
            target_gen_xp = base_gen_xp.rstrip("/") + actual_rel
            if not target_gen_xp:
                target_gen_xp = "/"

            matching = gen_xp_to_descendants.get(target_gen_xp)
            if not matching:
                continue

            vals: List[str] = []
            if key == "text()":
                for descendant in matching:
                    if descendant.tag in ("script", "style"):
                        continue
                    text_parts: List[str] = []
                    if descendant.text and descendant.text.strip():
                        text_parts.append(descendant.text.strip())
                    if descendant.tail and descendant.tail.strip():
                        text_parts.append(descendant.tail.strip())
                    if text_parts:
                        val = " ".join(text_parts).strip()
                        if val:
                            vals.append(val)
            else:
                attr_name = key[1:]  # strip leading '@'
                if attr_name == "contenteditable":
                    for descendant in matching:
                        v = descendant.get_attr(attr_name)
                        if v in ("true", ""):
                            vals.append("true")
                else:
                    for descendant in matching:
                        v = descendant.get_attr(attr_name)
                        if v and str(v).strip():
                            vals.append(str(v).strip())

            if vals:
                results.setdefault(full_route, []).extend(vals)
        else:
            # Intermediate relative-path segment — recurse.
            new_rel_path = current_rel_path + key
            _evaluate_trie(
                base_node, subtree, new_rel_path, base_gen_xp,
                node_to_gen_xpath, results, gen_xp_to_descendants,
            )
