"""The pipeline profiler, tested at each level it times.

The profiler attributes a page-to-pixels latency to stages, and an
attribution is only worth something if it can be WRONG in a detectable way.
So every level here has two arms, per `CLAUDE.md`:

* the clean arm -- the stage is timed, the figure is sane, the parts do not
  exceed the whole that contains them;
* the planted arm -- a known delay is injected into ONE stage and the
  profiler must put it in that stage and in no other. A profiler that spreads
  a planted 150 ms across its buckets, or reports it as noise, is not
  measuring anything, however plausible its clean numbers look.

Levels:

1. the store's sub-phases (`ms_chunks`, `ms_anchors`, ...), offline;
2. the sidecar's per-capture phases and its `/profile` rings, live;
3. the pane's end-to-end, closed by a listener that reads the 3D scene,
   live -- including the arm where a node is present in the data but NOT
   drawn, which the listener must refuse to count as visible.
"""

import json
import os
import pathlib
import time

import pytest

from vertiscope.workspace import Workspace

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"
LIVE = os.environ.get("VERTISCOPE_LIVE") == "1"


def _html(prefix="books-toscrape"):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith(prefix)), pages[0])
    return page["url"], (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")


def _render(ws, html, url):
    from vertiscope.core.content_tagger import ContentTagger
    from vertiscope.core.shadow_html_parser import ShadowDOM
    from vertiscope.markdown import RenderReport
    from vertiscope.trie import AddressTrie

    trie = AddressTrie.from_tagged(ContentTagger(ShadowDOM(html)).tag(), url)
    chunks, _ = ws.ingest(url, trie, report=RenderReport(), title="")
    return chunks


STORE_PHASES = ("ms_reconcile", "ms_addresses", "ms_chunks",
                "ms_anchors", "ms_contains", "ms_links",
                # Named after the profile showed `store` was only 63%
                # explained: the pre-queries before `_reconcile`, and the
                # workspace's own work around the graph write.
                "ms_prequery", "ms_settle", "ms_freq", "ms_page", "ms_mirror")


# --- level 1: the store's sub-phases -----------------------------------------


def _delta_counts(tmp_path, plant=None):
    """Ingest a page, then a delta of it, returning the delta's counts.

    `plant(query) -> seconds` delays any `_batch` whose statement it matches,
    which is how a known cost is put into exactly one timed phase.
    """
    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        ws.settle()
        chunks = _render(ws, html, url)
        if plant is not None:
            real = ws.store._batch

            def slowed(query, rows, *a, **k):
                pause = plant(query)
                if pause:
                    time.sleep(pause)
                return real(query, rows, *a, **k)

            ws.store._batch = slowed
        _written, counts = ws.ingest_chunks(url, chunks, complete=False)
        return counts


def test_the_store_reports_every_sub_phase(tmp_path):
    counts = _delta_counts(tmp_path)
    missing = [k for k in STORE_PHASES if k not in counts]
    assert not missing, "store phases not timed: %s" % missing
    for k in STORE_PHASES:
        assert counts[k] >= 0, (k, counts[k])


PLANT_S = 0.15          # well above the noise of any of these statements


@pytest.mark.parametrize("phase,marker", [
    ("ms_chunks", "MERGE (c:Chunk"),
    ("ms_anchors", "MERGE (a:Address"),
])
def test_a_planted_delay_lands_in_its_own_phase_and_no_other(
        tmp_path, phase, marker):
    """The non-vacuity arm: blame goes where the time actually went."""
    clean = _delta_counts(tmp_path / "clean")
    planted = _delta_counts(
        tmp_path / "planted",
        plant=lambda q: PLANT_S if marker in q else 0.0)

    grew = planted[phase] - clean[phase]
    assert grew >= PLANT_S * 1000 * 0.8, (
        "planted %d ms into %s and it grew by %.1f ms -- the profiler did "
        "not see it" % (PLANT_S * 1000, phase, grew))
    for other in STORE_PHASES:
        if other == phase:
            continue
        leaked = planted[other] - clean[other]
        assert leaked < PLANT_S * 1000 * 0.5, (
            "a delay planted in %s showed up in %s (+%.1f ms)"
            % (phase, other, leaked))


# --- level 2: the sidecar's phases, live --------------------------------------


needs_live = pytest.mark.skipif(not LIVE, reason="needs VERTISCOPE_LIVE=1, the "
                                "sidecar on 8788 and Obsidian on 9222")

SIDECAR_PHASES = ("decode", "absorb", "render", "store", "place")


@pytest.fixture(scope="module")
def profile():
    """One real run shared by the live assertions below: it costs ~40 s."""
    if not LIVE:
        pytest.skip("live")
    from vertiscope.obsidian.live import Live
    live = Live()
    live.reload_plugin()
    have = set(live.get("/pages").get("urls") or [])
    fresh = next((u for u in (
        "https://quotes.toscrape.com/page/%d/" % i for i in range(2, 11))
        if u not in have), "https://quotes.toscrape.com/page/10/")
    got = live.pipeline_profile(fresh, seconds=30, scrolls=6)
    got["_live"] = live
    return got


@needs_live
def test_the_run_is_trustworthy_before_anything_is_read(profile):
    """No figure is worth reading if the clocks or the join are broken."""
    checks = profile["checks"]
    assert checks["traces"] > 0, "no drain was traced at all"
    assert not checks["clock_inconsistent"], (
        "the sidecar reported more time than the round trip it happened in: "
        "%s" % checks["clock_inconsistent"])
    assert not checks["open_outcomes"], (
        "drains that never reached a named outcome -- a path the profiler "
        "does not close: %s" % checks["open_outcomes"])


@needs_live
def test_every_sidecar_phase_is_timed_and_sums_inside_the_total(profile):
    rings = profile["_live"].get("/profile")
    caps = rings.get("capture") or []
    assert caps, "the sidecar recorded no capture"
    for rec in caps:
        missing = [k for k in SIDECAR_PHASES if k not in rec]
        assert not missing, "phases missing from a capture: %s" % missing
        parts = sum(rec[k] for k in SIDECAR_PHASES)
        assert parts <= rec["total"] + 1.0, (
            "phases sum to %.1f ms inside a %.1f ms capture" % (parts, rec["total"]))


# --- level 3: the pane's end-to-end, closed by the scene listener --------------


@needs_live
def test_a_drain_reaches_the_screen_and_its_parts_fit_inside_it(profile):
    stages = (profile["pane"] or {}).get("stages") or {}
    assert "end_to_end" in stages, (
        "no drain was seen on screen: outcomes %s"
        % (profile["pane"] or {}).get("outcomes"))
    for trace in profile["sample"]:
        st = trace.get("stages") or {}
        if "end_to_end" not in st:
            continue
        # Renderer-clock stages are sequential within the end-to-end, so they
        # cannot add up to more than it.
        inside = sum(st.get(k, 0) for k in
                     ("drain", "capture", "vector_wait", "absorb", "visible"))
        assert inside <= st["end_to_end"] + 5.0, (
            "stages sum to %.1f ms inside a %.1f ms end-to-end"
            % (inside, st["end_to_end"]))


@needs_live
def test_the_listener_refuses_a_node_that_is_present_but_not_drawn(profile):
    """The non-vacuity arm for 'visible'.

    A node is put into the graph DATA with its scene object hidden. `absorb`
    would call that added; the listener must not call it visible, and the
    trace must end `not_seen`. If this passes as 'visible', the last stage
    of every profile has been measuring the diff rather than the picture.
    """
    live = profile["_live"]
    outcome = live.evaluate(r"""(async () => {
      const prof = window.__vertiscopeProfiler;
      const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view;
      const g = (v.projector || v).graph;
      const d = g.graphData();
      const probe = {id: '__listener_probe__', url: 'about:probe', level: 'chunk',
                     val: 1, x: 0, y: 0, z: 0, fitX: 0, fitY: 0, fitZ: 0};
      d.nodes.push(probe);
      g.graphData(d);
      await new Promise(r => setTimeout(r, 300));
      if (probe.__threeObj) probe.__threeObj.visible = false;
      const t = prof.begin('probe', 'about:probe');
      prof.watch(t, ['__listener_probe__'], performance.now(), 1500);
      await new Promise(r => setTimeout(r, 2200));
      const done = prof.list().find(x => x.id === t.id);
      // leave the graph as it was
      const after = g.graphData();
      after.nodes = after.nodes.filter(n => n.id !== '__listener_probe__');
      g.graphData(after);
      return done ? done.facts.outcome : 'never closed';
    })()""")
    assert outcome == "not_seen", (
        "a hidden node was counted as %r -- the listener is reading the "
        "data, not the scene" % outcome)
