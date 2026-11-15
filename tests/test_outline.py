"""A note unfolds by its own recursion (PLUGIN_GOAL 159).

"the navigation on cell hierarchies and unfolding on black box structures
still needs to be extended for the general compilation case ... any recursive
structures that we have already in our database for code, markdowns, etc, but
also including the notebook cells themselves as ego states."

`refs.outline` and `obsidian-plugin/src/outline.ts` are one grammar spelled
twice; both are held to `tests/fixtures/outline_expected.json`
(`obsidian-plugin/tests/outline.test.mjs` is the other half).
"""
import json
from pathlib import Path

from domvec.obsidian import refs

FX = Path(__file__).parent / "fixtures"
NOTE = (FX / "outline_note.md").read_text(encoding="utf-8")
EXPECTED = json.loads((FX / "outline_expected.json").read_text(encoding="utf-8"))


def test_every_address_unfolds_as_expected():
    for name, lines in EXPECTED.items():
        assert refs.outline(NOTE, name) == lines, name


def test_each_rank_names_the_next_and_every_named_rank_resolves():
    # Walk the whole tree from the note's root by the refs it reveals: every
    # `{Nb#...}` a rank shows must itself unfold -- no dead box.
    import re
    seen, todo = set(), ["Nb"]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        got = refs.outline(NOTE, n)
        assert got is not None, n
        todo += [m for l in got for m in re.findall(r"\{(Nb#[^}]+)\}", l)]
    # Headings, both cells' defs, the nested method: the tree is reached.
    assert {"Nb#Building#Insert", "Nb#cell 2#Node#child", "Nb#cell 3"} <= seen
    assert len(seen) == 11


def test_rank1_unfolds_by_outline_when_named_and_planted_flat_is_caught():
    named = refs.rank1(NOTE, name="Nb")
    assert named == EXPECTED["Nb"]
    refs.PLANT_FLAT_OUTLINE[0] = True
    try:
        flat = refs.rank1(NOTE, name="Nb")
    finally:
        refs.PLANT_FLAT_OUTLINE[0] = False
    # The flat reading never offers a section or a cell as a box.
    assert flat != named and not any("{Nb#" in l for l in flat)
    # Unnamed, rank1 keeps its old reading (slates, the cockpit's own refs).
    assert refs.rank1(NOTE) == flat


def test_a_slate_still_reads_as_its_fields():
    slate = "---\ndomvec: slate\n---\nego\n\tview\tego\n\tthrottle\t25\n"
    assert refs.rank1(slate, name="ego") == ["view\tego", "throttle\t25"]


def test_crlf_is_the_same_note():
    assert refs.outline(NOTE.replace("\n", "\r\n"), "Nb#cell 2") == EXPECTED["Nb#cell 2"]
