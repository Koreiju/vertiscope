"""What the kernel bootstrap does when a cell takes a core call's name
(THROUGH_STACK_SYNTHESIS 1g; G-240 "extensions ... may only tighten it").

Pinned as FOUND, not as intended: the bootstrap installs each core call only
when its name is free (`if "<name>" not in globals()`), so a cell's own
definition -- or a plain variable of that name -- replaces the core call for
the kernel's life, and nothing checks that it tightens anything. Enforcing
G-240 by re-installing would clobber readers' ordinary variables: `view`,
`check`, `types`, `pages`, `chunk`, `focus` are core names. Held for the
reader's decision.
"""

from domvec.obsidian import kernel_objects as ko


def _kernel():
    ns = {}
    exec(compile(ko.boot("http://127.0.0.1:9"), "<boot>", "exec"), ns)
    return ns


def test_a_cell_definition_replaces_a_core_call_for_good():
    ns = _kernel()
    core = ns["search"]
    exec("def search(q):\n    return 'mine'\n", ns)            # a cell
    exec(compile(ko.boot("http://127.0.0.1:9"), "<boot>", "exec"), ns)   # the next cell's bootstrap
    assert ns["search"] is not core and ns["search"]("x") == "mine"


def test_a_plain_variable_named_like_a_core_call_survives_too():
    ns = _kernel()
    exec("view = [1, 2, 3]\n", ns)
    exec(compile(ko.boot("http://127.0.0.1:9"), "<boot>", "exec"), ns)
    assert ns["view"] == [1, 2, 3]


def test_the_core_names_a_reader_could_collide_with():
    ns = _kernel()
    common = {"view", "check", "types", "pages", "chunk", "focus", "search", "similar", "answer", "browse"}
    assert common & set(ns) >= {"view", "check", "types", "pages", "chunk", "focus", "search", "similar", "browse"}
