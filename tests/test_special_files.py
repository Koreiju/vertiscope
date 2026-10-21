"""PLUGIN_GOAL 186k: special files a page links to -- .gguf, .csv, .json,
archives -- are content: detected at the linking line's address, stored per
chunk, listed per page."""
import vertiscope.workspace as wsmod
from vertiscope.workspace import Workspace

HTML = """<html><body><main>
<h2>Files</h2>
<ul>
<li><a href="/openjev/OpenJev-Flash-9B-GGUF/resolve/main/OpenJev-Flash-9B-Q4_K_M.gguf?download=true">OpenJev-Flash-9B-Q4_K_M.gguf</a></li>
<li><a href="https://data.example.org/sets/prices.csv">prices.csv</a></li>
<li><a href="https://data.example.org/dump.tar.gz">dump</a></li>
<li><a href="https://example.org/about.html">about</a></li>
<li><a href="https://arxiv.org/pdf/2401.0001v2/paper.pdf">the paper</a></li>
</ul></main></body></html>"""


def test_files_detected_resolved_and_kept_per_page(tmp_path, monkeypatch):
    url = "https://huggingface.co/openjev/OpenJev-Flash-9B-GGUF/tree/main"
    got = {}
    for planted in (False, True):
        monkeypatch.setattr(wsmod, "_PLANT_NO_FILES", planted)
        with Workspace(tmp_path / ("p" if planted else "c")) as ws:
            ws.index_html(HTML, url)
            got[planted] = ws.store.files_of(url)
    files = {f["name"]: f for f in got[False]}
    assert set(files) == {"OpenJev-Flash-9B-Q4_K_M.gguf", "prices.csv", "dump.tar.gz", "paper.pdf"}, files
    g = files["OpenJev-Flash-9B-Q4_K_M.gguf"]
    assert g["kind"] == "model" and g["ext"] == ".gguf"
    assert g["href"].startswith("https://huggingface.co/openjev/OpenJev-Flash-9B-GGUF/resolve/main/")  # page-relative, resolved
    assert files["dump.tar.gz"]["kind"] == "archive" and files["prices.csv"]["kind"] == "table"
    assert files["paper.pdf"]["kind"] == "pdf"
    assert all(f["cid"] and f["xpath"] for f in got[False])
    assert got[True] == []                                    # planted: nothing detected


def test_a_recapture_replaces_a_chunks_files(tmp_path):
    url = "https://data.example.org/"
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, url)
        assert len(ws.store.files_of(url)) == 4
        ws.index_html(HTML.replace('<li><a href="https://data.example.org/sets/prices.csv">prices.csv</a></li>', ""), url)
        names = {f["name"] for f in ws.store.files_of(url)}
        assert "prices.csv" not in names and "dump.tar.gz" in names


def test_a_hugging_face_viewer_link_is_taken_as_its_file(tmp_path, monkeypatch):
    """`/blob/` is the viewer page, `/resolve/` the file; listed both ways, the
    file is ONE node at its `/resolve/` address. Planted `_PLANT_HF_BLOB`: the
    viewer page is taken (its HEAD read 198 KB for a 5.63 GB GGUF)."""
    html = ('<html><body><main><ul><li><a href="/o/r/blob/main/m-Q4_K_M.gguf">m-Q4_K_M.gguf</a> '
            '<a href="/o/r/resolve/main/m-Q4_K_M.gguf?download=true">download</a></li></ul></main></body></html>')
    url = "https://huggingface.co/o/r/tree/main"
    got = {}
    for planted in (False, True):
        monkeypatch.setattr(wsmod, "_PLANT_HF_BLOB", planted)
        with Workspace(tmp_path / ("p" if planted else "c")) as ws:
            ws.index_html(html, url)
            got[planted] = [f["href"] for f in ws.store.files_of(url)]
    assert got[False] == ["https://huggingface.co/o/r/resolve/main/m-Q4_K_M.gguf"], got
    assert any("/blob/" in h for h in got[True]), got
