"""A notebook cell's output stays out of every search scope but `ego` (T-13).

PLUGIN_GOAL 145: a cell's OUTPUT is retrievable in the ego scope only. The
search route reads that off the stored CHUNK's xpath (`/output`), which only
works if the chunker never merges the output with the note around it.
`markdown.render_trie` merges small siblings, so before 2026-11-15 a short
notebook note -- a heading, a python fence and its `nb-output` block --
rendered to ONE chunk at `/` holding `# Cell / print(41 + 1) / 42`, and the
rule never fired: an `all` search for the output's text found it.

The fix is the slate's `state` boundary (`markdown._holds_state`), extended
to `output` steps on `vault://` pages: a subtree holding one is never taken
whole, and the output stands alone as a record.

Planted `markdown.PLANT_NO_OUTPUT_BOUNDARY`: the output merges back into the
cell's chunk, and the `all` search finds it again.
"""
import pytest

from domvec import markdown as M
from domvec.obsidian import sidecar as S
from domvec.obsidian.sidecar import search_payload
from domvec.vault import note_url
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder

# The output's text shares no word with the source or the heading, so a hit
# on it can only be the output -- or a chunk the output was merged into.
NOTE = """# Cell

```python
print(zircon_lattice_constant())
```
<!-- nb-output hash=deadbeef count=1 status=ok format=text -->
````text
quasicrystal penrose tiling aperiodic
````
<!-- /nb-output -->
"""
REL = "nb/short.md"
QUERY = "quasicrystal penrose tiling aperiodic"

PAGE = ("<html><body><main><h2>Tilings</h2><p>A penrose tiling is aperiodic; "
        "a quasicrystal has the same order.</p></main></body></html>")


def _chunks(w, url):
    return [c for c in w.store.chunks() if c.url == url]


@pytest.mark.parametrize("planted", [False, True])
def test_the_output_is_its_own_chunk(tmp_path, planted, monkeypatch):
    monkeypatch.setattr(M, "PLANT_NO_OUTPUT_BOUNDARY", planted)
    url = note_url("vault", REL)
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_note(NOTE, REL)
        chunks = _chunks(w, url)
    holding = [c for c in chunks if "quasicrystal" in (c.md or "")]
    assert len(holding) == 1, [(c.xpath, c.md) for c in chunks]
    out = holding[0]
    if planted:
        # The defect, reproduced: one chunk, not under `/output`, holding the
        # source as well.
        assert "/output" not in str(out.xpath) and "zircon" in out.md, (out.xpath, out.md)
    else:
        assert "/output" in str(out.xpath), (out.xpath, out.md)
        assert "zircon" not in out.md, out.md
        # The cell's source is still a chunk of its own.
        assert any("zircon" in (c.md or "") for c in chunks if c is not out), [c.md for c in chunks]


@pytest.mark.parametrize("planted", [False, True])
def test_an_output_is_found_in_the_ego_scope_only(tmp_path, monkeypatch, planted):
    monkeypatch.setattr(M, "PLANT_NO_OUTPUT_BOUNDARY", planted)
    url = note_url("vault", REL)
    # The note is in the ego set. `ego_load` reads `ego.json`; stubbed so the
    # set is exactly this note.
    monkeypatch.setattr(S, "EGO", {"urls": {url}, "cids": set(), "loaded": "stub"})
    monkeypatch.setattr(S, "ego_load", lambda _ws: None)
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html(PAGE, "https://tilings.test/")
        w.index_note(NOTE, REL)
        w.flush_vectors()
        every = search_payload(w, QUERY, 5, where="all")
        ego = search_payload(w, QUERY, 5, where="ego")
    every_urls = [h["url"] for h in every["hits"]]
    ego_hits = [(h["url"], h["xpath"]) for h in ego["hits"]]
    if planted:
        # Merged into the cell's chunk, the output escapes T-13.
        assert url in every_urls, every_urls
        return
    assert url not in every_urls and every_urls and every_urls[0] == "https://tilings.test/", every_urls
    assert any(u == url and "/output" in str(x) for u, x in ego_hits), ego_hits


def test_output_on_a_web_page_is_not_a_boundary(tmp_path):
    """`output` is an HTML element; the boundary is the vault reader's."""
    html = ("<html><body><main><p>Sum of two</p><output>42 apples</output>"
            "<p>and more</p></main></body></html>")
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html(html, "https://out.test/")
        chunks = _chunks(w, "https://out.test/")
    holding = [c for c in chunks if "apples" in (c.md or "")]
    assert len(holding) == 1 and "Sum of two" in holding[0].md, [(c.xpath, c.md) for c in chunks]
