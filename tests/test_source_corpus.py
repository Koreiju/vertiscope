"""The local codebase in the trie, and what may be vectorised out of it.

`G-49` asks for the codebase beside the web scans and the vault. `G-52` says
what reaches the encoder: *"only vectorizing comments and docstrings and not
the actual code itself"*.

The separation is a property of the RENDER, not of a second parse:
`vertiscope.source` emits docstrings, comments and names as prose and code as a
code span, so honouring `G-52` is one flag on `tokens.for_model`. That design
is what makes it testable at all -- there is one string the encoder gets, and
it can be asked what is in it.

**The arm that matters is the leak arm.** A stripper that removed everything
would satisfy "no code reaches the encoder" perfectly and be useless, so
every test here also asserts that the PROSE survived. The first version of
the stripper knew only about fenced blocks, removed 0% of a real source file,
and reported success -- `markdown.py` renders a code detection as an inline
span, not a fence.
"""

import pathlib
import shutil
import tempfile

import pytest

from vertiscope import tokens
from vertiscope.source import SKIP_DIRS, source_path_of, source_url, tag_source
from vertiscope.workspace import Workspace

SAMPLE = '''"""A module that explains itself."""

import os


class Widget:
    """A widget holds a spindle."""

    def spin(self, revolutions):
        """Turn the spindle."""
        # the spindle is fragile above ten thousand
        return revolutions * 2
'''


@pytest.fixture()
def ws():
    tmp = tempfile.mkdtemp()
    try:
        with Workspace(pathlib.Path(tmp) / "ws") as got:
            yield got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- addressing --------------------------------------------------------------


def test_the_url_round_trips():
    url = source_url("vertiscope", "vertiscope/aggregate.py")
    assert url == "code://vertiscope/vertiscope/aggregate.py"
    assert source_path_of(url) == ("vertiscope", "vertiscope/aggregate.py")
    assert source_path_of("https://example.com/") is None


def test_windows_separators_become_one_spelling():
    """A path spelled two ways is two addresses, which is two of everything."""
    assert source_url("r", "a\\b\\c.py") == source_url("r", "a/b/c.py")


def test_the_xpath_is_the_module_s_own_tree():
    tags = tag_source(SAMPLE)
    paths = [t.xpath for t in tags]
    assert "/module[1]/docstring[1]" in paths
    # A class CONTAINS its methods -- unlike a markdown heading, which only
    # names the section it opens (see `vertiscope/vault.py`'s section wrapper).
    assert any(p.startswith("/module[1]/class[1]/function[1]/") for p in paths)
    assert "/module[1]/class[1]/docstring[1]" in paths


def test_a_file_that_does_not_parse_still_yields_its_comments():
    """A syntax error is an ordinary state for a file being edited.

    Refusing it would make the corpus a function of whether the working tree
    happens to compile.
    """
    broken = "# a standing comment\ndef oops(:\n    pass\n"
    tags = tag_source(broken)
    assert any("a standing comment" in (t.value or "") for t in tags)


# --- G-52 --------------------------------------------------------------------


def test_code_does_not_reach_the_encoder_and_prose_does(ws):
    """Both arms, because either alone is satisfied by a broken stripper."""
    got = ws.index_source(SAMPLE, "pkg/widget.py", root="repo")
    assert got.url.startswith("code://")
    rendered = "\n".join(c.md or "" for c in ws.store.chunks(got.url))
    assert rendered.strip(), "nothing was rendered"

    seen = tokens.for_model(rendered, drop_code=True)

    # The code is in the chunk a reader opens...
    assert "revolutions * 2" in rendered
    # ...and not in the string the encoder is charged for.
    assert "revolutions * 2" not in seen, "code reached the encoder"
    assert "import os" not in seen

    # And the prose did survive. Without this a stripper that returned ""
    # would pass every assertion above.
    assert "A widget holds a spindle" in seen
    assert "Turn the spindle" in seen
    assert "the spindle is fragile" in seen, "a comment was dropped"


def test_the_flag_is_off_for_everything_that_is_not_source():
    """A web page's code sample is part of what that page says.

    Dropping it by default would change every existing embedding in the
    corpus to serve a requirement about source files.
    """
    page = "Here is how you call it: `client.connect()` and then wait."
    assert "client.connect()" in tokens.for_model(page)
    assert "client.connect()" not in tokens.for_model(page, drop_code=True)


def test_the_budget_counts_the_string_the_encoder_gets(ws):
    """`G-22`'s argument, restated one domain over.

    A budget enforced on one string and spent on another is not a budget.
    """
    rendered = "prose about it\n\n`def f(x): return x + 1`\n\nmore prose"
    plain = tokens.budget_for(rendered, "https://example.com/")
    code = tokens.budget_for(rendered, "code://repo/f.py")
    assert code < plain, "the code:// budget counted the code anyway"


def test_the_stripper_is_not_simply_deleting_everything():
    """The non-vacuity arm for the stripper itself."""
    prose = "One merged chunk holds the cids it is made of, in document order."
    assert tokens.for_model(prose, drop_code=True).strip() == prose


# --- the walk ----------------------------------------------------------------


def test_the_skip_list_keeps_the_corpus_out_of_its_own_artifacts():
    """`build/` here holds multi-gigabyte stores and `__pycache__` holds
    compiled copies of the very files being indexed."""
    for name in ("build", "__pycache__", ".git", "node_modules"):
        assert name in SKIP_DIRS


def test_web_vault_and_code_share_one_trie(ws):
    """`G-11`: three sources in one skeleton, not three pipelines.

    The whole reason `vertiscope.source` defines its addressing to LOOK like a
    page's is so that everything downstream -- `from_tags`, the chunker, the
    frequency rows, the graph -- is reused rather than duplicated. The proof
    of that is one store holding all of them, keyed the same way.
    """
    ws.index_html("<html><body><p>a page about spindles</p></body></html>",
                  "https://example.test/spindles")
    ws.index_note("# A note\n\nProse about the spindle.\n", "notes/spindle.md")
    ws.index_source(SAMPLE, "pkg/widget.py", root="repo")
    ws.index_source(SAMPLE, "numpy/_util.py", root="pypi/numpy")

    schemes = {u.split("://")[0] for u in
               {c.url for c in ws.store.chunks()}}
    assert schemes == {"https", "vault", "code"}, schemes

    # And the addresses are one trie, not four -- every chunk resolves the
    # same way whatever it came from.
    for chunk in ws.store.chunks():
        assert chunk.xpath.startswith("/"), chunk.url


# --- G-8 / G-51: an import is a link -----------------------------------------


def test_an_import_becomes_an_edge_through_the_hyperlink_path(ws):
    """`G-8`, `G-51`: *"dependencies are tracked throughout"*.

    Not a second graph. An import is categorised as a link, so
    `ContentAddress.is_url` says so, the store's existing `_link_pages`
    resolver picks it up, `edges()` routes it and PageRank counts it -- the
    same treatment a hyperlink gets. That reuse is the whole reason for
    spending an address on it rather than keeping a side table.
    """
    lib = '"""A library."""\n\n\ndef helper():\n    """Help."""\n    return 1\n'
    app = ('"""An app."""\n\nfrom pkg import lib\n\n\n'
           'def main():\n    """Run it."""\n    return lib.helper()\n')
    ws.index_source(lib, "pkg/lib.py", root="repo")
    ws.index_source(app, "pkg/app.py", root="repo")

    pairs = set(ws.store.page_links())
    assert ("code://repo/pkg/app.py", "code://repo/pkg/lib.py") in pairs, pairs


def test_a_dependency_on_a_module_indexed_LATER_is_repaired(ws):
    """The ingest-order limitation, and why `relink` exists.

    A link resolves once, against the pages the store held at that moment.
    Index the importer first and the edge cannot be written, because its
    target does not exist yet. Measured on `vertiscope/` itself: 96 edges at
    ingest, 223 after `relink` -- more than double.
    """
    app = '"""An app."""\n\nfrom pkg import lib\n\n\ndef main():\n    """Go."""\n    return 1\n'
    lib = '"""A library."""\n\n\ndef helper():\n    """Help."""\n    return 1\n'
    ws.index_source(app, "pkg/app.py", root="repo")     # importer FIRST
    ws.index_source(lib, "pkg/lib.py", root="repo")

    want = ("code://repo/pkg/app.py", "code://repo/pkg/lib.py")
    assert want not in set(ws.store.page_links()), \
        "the edge existed before relink, so this proves nothing"

    got = ws.store.relink()
    assert got["resolvable"] >= 1, got
    assert want in set(ws.store.page_links()), "relink did not repair it"


# --- G-50: the fold itself is JavaScript -------------------------------------


def test_a_comment_marker_inside_a_string_is_not_a_comment():
    """The one thing a line-based scan gets wrong, and this one does not.

    `sensor.js` is full of urls in string literals, so a scan that counted
    every `//` would report hundreds of comments that are not there and feed
    the encoder fragments of urls.
    """
    from vertiscope.source import _js_comments

    src = 'const u = "http://example.com/x";  // the real one\n'
    got = _js_comments(src)
    assert [body for _row, body in got] == ["the real one"], got


def test_a_template_literal_spanning_lines_does_not_swallow_comments():
    from vertiscope.source import _js_comments

    src = "const t = `a\nb`;\n// after the template\n"
    assert [b for _r, b in _js_comments(src)] == ["after the template"]


def test_a_jsdoc_block_loses_its_leading_stars():
    """The encoder should be charged for the prose, not the punctuation."""
    from vertiscope.source import _js_comments

    src = "/**\n * A factory expression.\n * Not a self-invocation.\n */\n"
    got = [b for _r, b in _js_comments(src)]
    assert got == ["A factory expression.\nNot a self-invocation."], got


def test_javascript_gives_its_comments_to_the_encoder_and_not_its_code(ws):
    """`G-50`: the script that runs the scan is a chunk like any other."""
    src = ('// the fold reads no layout\n'
           'function fold(node) {\n'
           '  const seen = new Set();\n'
           '  return seen;\n'
           '}\n')
    got = ws.index_source(src, "core/js/sensor.js", root="repo")
    rendered = "\n".join(c.md or "" for c in ws.store.chunks(got.url))
    seen = tokens.for_model(rendered, drop_code=True)

    assert "the fold reads no layout" in seen, "the comment was lost"
    assert "new Set()" in rendered
    assert "new Set()" not in seen, "code reached the encoder"


# --- G-10: the vault has edges too -------------------------------------------


def test_a_relative_link_resolves_under_a_local_scheme():
    """`urljoin` refuses to do this, and silently.

    It only performs relative resolution for schemes it knows, so
    `urljoin("vault://v/a.md", "b.md")` hands back `"b.md"` unchanged -- not
    an error, just the input. Every vault link therefore resolved to nothing
    and the vault had no edges at all.
    """
    from vertiscope.graphstore import canonical_url

    assert canonical_url("Lattice.md", "vault://vault/Spindle.md") \
        == "vault://vault/Lattice.md"
    assert canonical_url("../Other.md", "vault://vault/a/b.md") \
        == "vault://vault/Other.md"
    assert canonical_url("lib.py", "code://repo/pkg/app.py") \
        == "code://repo/pkg/lib.py"
    # And the web path is untouched.
    assert canonical_url("/x", "https://a.test/y") == "https://a.test/x"


def test_a_wikilink_alone_becomes_an_edge(ws):
    """`[[Lattice]]` names a NOTE; the note is a file.

    Offering the `.md` spelling is the only vault-specific rule here -- the
    store's own rule still decides, so a wikilink to a note nobody has
    indexed stays an address and does not become an edge.
    """
    ws.index_note("# Lattice\n\nProse about lattices.\n", "Lattice.md")
    ws.index_note("# Spindle\n\nOnly a wikilink: [[Lattice]].\n", "Spindle.md")
    ws.store.relink()

    pairs = set(ws.store.page_links())
    assert ("vault://vault/Spindle.md", "vault://vault/Lattice.md") in pairs, pairs


def test_a_wikilink_to_a_note_that_is_not_indexed_stays_an_address(ws):
    """The non-vacuity arm: the `.md` rule must not invent a target."""
    ws.index_note("# Spindle\n\nA link to [[Nowhere]].\n", "Spindle.md")
    ws.store.relink()
    assert not [p for p in ws.store.page_links() if "Nowhere" in p[1]]
