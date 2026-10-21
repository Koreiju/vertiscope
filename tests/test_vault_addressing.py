"""A vault note in the trie (`T-5`).

The point of these is not that markdown parses. It is that a note's addresses
come out in a shape the *existing* pipeline already reads — the chunker, the
renderer, the frequency rows, retrieval — because reusing that pipeline is the
whole reason the vault goes in the trie rather than beside it.

So the load-bearing test is `test_prose_is_not_drawn_as_a_heading`: it asserts
against `markdown.py`'s real output, and it fails on the addressing scheme that
looks obviously right.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from vertiscope.vault import note_path_of, note_url, tag_note


NOTE = """# Analysis

Prose about superconductivity and flux pinning.

## Method

We measured the critical current density.

```python
df.describe()   # a # that is not a heading
## neither is this
```

- flux pinning is the mechanism
- see [[Vortex Lattice]] and [docs](https://example.com)

## Results

> a quotation

Final prose.
"""


def _by_xpath(tags):
    return {t.xpath: t for t in tags}


# --- the url ----------------------------------------------------------------


def test_note_url_round_trips_through_a_windows_path():
    """Separators are normalised once, in `note_url`, not at every call site.

    A url may not carry a backslash, and on this platform every path arrives
    with them.
    """
    import os
    rel = os.path.join("notes", "analysis.md")
    url = note_url("vertiscope", rel)
    assert url == "vault://vertiscope/notes/analysis.md"
    assert note_path_of(url) == ("vertiscope", "notes/analysis.md")


def test_the_vault_is_the_origin_and_the_path_is_segments():
    """`url_steps` decides how a global trie groups these.

    The vault has to be the origin so notes group by vault before they group by
    folder — the same reason a site's origin leads for a page.
    """
    from vertiscope.address import url_steps
    steps = url_steps(note_url("vertiscope", "a/b/c.md"))
    assert steps == ("vault://vertiscope", "a", "b", "c.md"), steps


def test_a_leading_separator_does_not_become_a_netloc():
    """`vault://v//notes` would split with an empty first segment.

    Worse, a path handed in as absolute-looking is the common case from a file
    picker, so this is not a corner.
    """
    assert note_url("v", "/notes/x.md") == "vault://v/notes/x.md"


def test_note_path_of_refuses_a_web_url():
    """It returns None rather than guessing, because a caller uses the answer
    to open a file and a guess would open the wrong one."""
    assert note_path_of("https://example.com/a") is None
    assert note_path_of("vault://onlyavault") is None


# --- the addressing ---------------------------------------------------------


def test_a_heading_opens_a_section_and_does_not_contain_it():
    """Blocks are SIBLINGS of their heading, inside a shared `section`.

    This is the shape the renderer needs; `test_prose_is_not_drawn_as_a_heading`
    is why.
    """
    paths = set(_by_xpath(tag_note(NOTE)))
    assert "/section[1]/h1[1]" in paths
    assert "/section[1]/p[1]" in paths, "prose must be a sibling of the h1"
    assert not any(p.startswith("/section[1]/h1[1]/") for p in paths), \
        "nothing may hang UNDER a heading step"


def test_sections_nest_and_siblings_number_independently():
    paths = set(_by_xpath(tag_note(NOTE)))
    assert "/section[1]/section[1]/h2[1]" in paths      # ## Method
    assert "/section[1]/section[2]/h2[1]" in paths      # ## Results
    # Each section counts its own h2 from 1. If the counters were global the
    # second would be h2[2] and its address would not say which section it
    # heads.
    assert "/section[1]/section[2]/h2[2]" not in paths


def test_a_closed_section_does_not_leave_its_counters_behind():
    """Two sibling sections each holding one paragraph.

    If closing a section kept its `(parent, kind)` counters, the second
    section's paragraph would be `p[2]` at a path where there is no `p[1]` --
    an address for content the note does not have.
    """
    tags = tag_note("## A\n\nfirst\n\n## B\n\nsecond\n")
    paths = set(_by_xpath(tags))
    assert "/section[1]/p[1]" in paths
    assert "/section[2]/p[1]" in paths
    assert "/section[2]/p[2]" not in paths


def test_content_before_any_heading_still_gets_an_address():
    """A note may open with prose, and frontmatter always precedes a heading.

    The implicit root section is what gives them somewhere to live; without it
    the first block has no parent.
    """
    tags = tag_note("---\ntags: [x]\n---\n\nopening prose\n\n# Later\n")
    kinds = {t.xpath: t.subcategory for t in tags}
    assert "/frontmatter[1]" in kinds
    assert kinds["/frontmatter[1]"] == "metadata"
    assert "/p[1]" in kinds, "prose before the first heading"


def test_a_fence_is_verbatim_and_its_hashes_are_not_headings():
    """The scanner consumes to the closing fence rather than re-dispatching
    each line, so `#` inside code is code."""
    tags = _by_xpath(tag_note(NOTE))
    code = tags["/section[1]/section[1]/code[1]"]
    assert code.subcategory == "code"
    assert "## neither is this" in code.value
    # and no heading was minted from inside it
    assert "/section[1]/section[1]/section[1]" not in tags


def test_an_inline_link_is_its_own_element():
    """`…/li[2]/a[1]`, not the li's own address.

    Sharing the block's address made the renderer consume the whole paragraph
    as one link label: `[see [[Vortex Lattice]]](Vortex Lattice)`.
    """
    tags = _by_xpath(tag_note(NOTE))
    links = {p: t for p, t in tags.items() if t.category == "urls"}
    assert links, "the note has two links"
    assert all("/a[" in p for p in links), links
    assert any(t.value == "https://example.com" and t.subcategory == "external"
               for t in links.values())
    assert any(t.value == "Vortex Lattice" and t.subcategory == "internal"
               for t in links.values()), "a wikilink points inside the vault"


def test_every_address_has_a_class_the_pipeline_knows():
    """New SUBcategories are safe; a new CATEGORY would not be.

    `address._CLASS_BY_CATEGORY` is what makes every address classifiable, and
    it is keyed on the category. `text.code` is new and falls back correctly;
    `markdown.code` would not.
    """
    from vertiscope.address import address_of
    for tag in tag_note(NOTE):
        cls = address_of(tag, note_url("v", "n.md")).render_class
        assert cls, f"{tag.category}.{tag.subcategory} has no class"


# --- the thing the addressing exists for ------------------------------------


def test_prose_is_not_drawn_as_a_heading():
    """The load-bearing assertion, against `markdown.py`'s real output.

    `markdown.py`'s walk carries a heading's label down to its children, on
    purpose and correctly for HTML: `<h3><div>Technology</div></h3>` means the
    div IS heading text. Markdown's heading does not contain the section it
    opens, so hanging blocks under a heading step asserts containment markdown
    never meant -- and every paragraph comes out as `# Prose about…`.

    This is the non-vacuity arm for the `section` wrapper. Remove the wrapper
    as an obvious simplification and this fails; the shape tests above would
    all still pass.
    """
    with tempfile.TemporaryDirectory() as td:
        from vertiscope.workspace import Workspace
        ws = Workspace(pathlib.Path(td) / "ws")
        try:
            ws.index_note(NOTE, "notes/analysis.md", vault="vertiscope")
            rendered = "\n".join(c.md for c in ws.store.chunks())
        finally:
            ws.close()

    lines = [l.strip() for l in rendered.splitlines() if l.strip()]
    headings = [l for l in lines if l.startswith("#")]
    assert headings, "the note has three headings"
    # Exactly the note's own headings, and nothing else, carry a hash.
    assert sorted(headings) == sorted(["# Analysis", "## Method", "## Results"]), \
        f"something that is not a heading was drawn as one: {headings}"
    # And the prose is present as prose.
    assert any(l.startswith("Prose about") for l in lines), lines
    assert any(l.startswith("- flux pinning") for l in lines), lines
    assert any(l.startswith("> a quotation") for l in lines), lines


def test_a_note_is_retrievable_after_indexing():
    """The acceptance bar for `T-5`: in the trie means FINDABLE.

    An address nothing can retrieve would satisfy every structural test here
    and none of the requirement.
    """
    with tempfile.TemporaryDirectory() as td:
        from vertiscope.workspace import Workspace
        ws = Workspace(pathlib.Path(td) / "ws")
        try:
            result = ws.index_note(NOTE, "notes/analysis.md", vault="vertiscope")
            assert result.url == "vault://vertiscope/notes/analysis.md"
            assert result.addresses > 0 and result.chunks > 0
            assert ws.stats()["freq_rows"] > 0, "no frequency row, so no retrieval"

            hits = ws.search("flux pinning", k=3)
            assert hits, "the note's own words did not retrieve it"
            assert any(h.url == result.url for h in hits)

            # Non-vacuity: a query the note does not answer must not match it.
            # Without this, a retrieval that returns everything passes above.
            assert not any(h.url == result.url
                           for h in ws.search("kubernetes helm chart", k=3))
        finally:
            ws.close()


# --- stored cell outputs (step 4's side of the trie) ------------------------


OUTPUT_NOTE = """# Measurements

```python
print("critical current density")
```
<!-- nb-output hash=deadbeef count=1 status=ok format=text -->
````text
critical current density 4.2e6
````
<!-- /nb-output -->
"""


def test_an_html_comment_is_not_visible_text():
    """Every renderer hides these, so by the affine-map rule they are not seen.

    It arrived as a real defect, not a principle: tagging the markers as
    paragraphs put `hash=`, `count=` and `status=ok` into the chunk's own text,
    so a search for "nb-output hash status" retrieved the note and every
    notebook note's vector carried the same bookkeeping tokens.
    """
    values = [t.value for t in tag_note(OUTPUT_NOTE)]
    assert not any("nb-output" in v for v in values), values
    assert not any("hash=" in v for v in values), values


def test_a_stored_output_is_still_addressed():
    """Skipping the MARKERS must not skip the output.

    The non-vacuity partner of the test above: dropping the whole block would
    satisfy it and lose the thing the block exists to carry. §1 chose
    outputs-in-markdown so that an output is trie content; if it is not
    addressed, that choice bought nothing.
    """
    tags = {t.xpath: t for t in tag_note(OUTPUT_NOTE)}
    outputs = [t for t in tags.values() if t.subcategory == "output"]
    assert len(outputs) == 1, tags
    assert "4.2e6" in outputs[0].value, outputs[0].value


def test_an_output_is_labelled_apart_from_the_cell_that_made_it():
    """`output`, not `code`, and the reason is the renderer.

    `markdown.py` merges adjacent same-label runs. With both labelled `code`,
    the cell's source and its result came out as ONE line --
    `print("…") critical current density 4.2e6` -- so a reader could not tell
    what was run from what came back.
    """
    tags = {t.xpath: t for t in tag_note(OUTPUT_NOTE)}
    assert "/section[1]/code[1]" in tags, tags
    assert "/section[1]/output[1]" in tags, tags
    assert tags["/section[1]/code[1]"].subcategory == "code"
    assert tags["/section[1]/output[1]"].subcategory == "output"


def test_the_output_renders_on_its_own_line():
    """Asserted against `markdown.py`, because the label exists for its sake."""
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from vertiscope.workspace import Workspace
        ws = Workspace(pathlib.Path(td) / "ws")
        try:
            ws.index_note(OUTPUT_NOTE, "m.md", vault="v")
            rendered = "\n".join(c.md for c in ws.store.chunks())
        finally:
            ws.close()

    lines = [l.strip() for l in rendered.splitlines() if l.strip()]
    source = [l for l in lines if "print(" in l]
    output = [l for l in lines if "4.2e6" in l]
    assert source and output, lines
    assert source[0] != output[0], f"source and output merged: {lines}"
    assert "nb-output" not in rendered, rendered


def test_an_unclosed_comment_does_not_swallow_the_note():
    """A truncated write must cost the comment, not the rest of the document."""
    tags = tag_note("# T\n\n<!-- nb-output hash=x\n\nprose after\n")
    values = [t.value for t in tags]
    assert any("prose after" == v for v in values), values


# --- where the chunker cut (P-N8, step 7) -----------------------------------


def _long_note(sections=4, paras=3):
    """A note that certainly exceeds a 256-token window several times."""
    body = ("flux pinning in a type II superconductor carries current without "
            "resistance below its critical temperature, and the vortex lattice "
            "is what holds it there. ") * 4
    lines = ["# Long note", ""]
    for s in range(1, sections + 1):
        lines += [f"## Section {s}", ""]
        for p in range(1, paras + 1):
            lines += [f"Paragraph {s}.{p}. {body}", ""]
    return "\n".join(lines)


def test_the_line_map_spans_the_block_it_addresses():
    """`tag_note`'s out-parameter, which is the whole basis of the gutter.

    Only this pass knows both the address and the source line; a chunk knows its
    addresses and nothing about where they were written.
    """
    text = "# H\n\nfirst\nsecond\n\n## S\n\n```py\na\nb\n```\n"
    at = {}
    tag_note(text, lines_at=at)
    assert at["/section[1]/h1[1]"] == (0, 0)
    # A paragraph is the one block whose extent is unknown when it starts.
    assert at["/section[1]/p[1]"] == (2, 3), at
    assert at["/section[1]/section[1]/h2[1]"] == (5, 5)
    # A fence spans its own delimiters.
    assert at["/section[1]/section[1]/code[1]"] == (7, 10), at


def test_preview_agrees_with_what_indexing_stores():
    """The load-bearing assertion for step 7.

    The gutter shows boundaries computed from the text on screen rather than
    read back from the store, because a stored boundary is stale from the first
    keystroke. That is only safe because it is the SAME pipeline -- `tag_note`,
    `from_tags`, `render_trie` -- with the store write left out. If the two ever
    disagree, the gutter is confidently telling the reader something untrue
    about their own note, which is worse than showing nothing.
    """
    from vertiscope.vault import chunk_preview

    text = _long_note()
    preview = chunk_preview(text, "n.md", vault="v")

    with tempfile.TemporaryDirectory() as td:
        from vertiscope.workspace import Workspace
        ws = Workspace(pathlib.Path(td) / "ws")
        try:
            ws.index_note(text, "n.md", vault="v")
            stored = ws.store.chunks()
        finally:
            ws.close()

    assert len(preview) > 1, "the fixture must actually split, or this proves nothing"
    assert sorted((c["xpath"], c["part"]) for c in preview) == \
           sorted((c.xpath, c.part) for c in stored)


def test_every_previewed_span_is_inside_the_note_and_ordered():
    """A span off the end would put a mark on a line that is not there.

    Ordered by first line, because that is the order a reader meets them in --
    the chunker emits by trie descent, which is not the same thing.
    """
    from vertiscope.vault import chunk_preview

    text = _long_note()
    last = len(text.splitlines()) - 1
    spans = chunk_preview(text, "n.md")
    for c in spans:
        assert 0 <= c["start_line"] <= c["end_line"] <= last, c
    assert spans == sorted(spans, key=lambda c: (c["start_line"], c["end_line"]))


def test_spans_do_not_overlap():
    """Two chunks claiming one line would draw two marks on it.

    Worse than cosmetic: the gutter's whole claim is that a mark says which
    chunk a line belongs to, and a line in two chunks has no answer.
    """
    from vertiscope.vault import chunk_preview

    spans = chunk_preview(_long_note(), "n.md")
    for a, b in zip(spans, spans[1:]):
        assert a["end_line"] < b["start_line"], (a, b)


def test_the_window_is_reported_and_over_window_is_flagged():
    """`S-11` is Partial for exactly this case, so the reader should see it."""
    from vertiscope.vault import chunk_preview

    spans = chunk_preview(_long_note(), "n.md", context_window=64)
    assert all(c["window"] == 64 for c in spans)
    # At 64 tokens a paragraph of this size cannot fit, so something must be
    # flagged -- otherwise the flag is never exercised and cannot be trusted.
    assert any(c["over_window"] for c in spans), spans[:3]
    for c in spans:
        assert c["over_window"] == (c["tokens"] > 64), c
