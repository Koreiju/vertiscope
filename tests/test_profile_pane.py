"""The pipeline profile readout shows what the profiler measured -- and changes.

It is not a pane any more (`G-76`): it is a section of the corner box over
the Electron browser, opened with the harness's `pipebox` gesture -- the same
state a reader's click sets.

A pane that displays numbers can be wrong in two ways a screenshot will not
catch: it can show a figure the profiler never produced, and it can keep
showing an old figure after the data moved on. Both are checked here against
the profiler's own summary, read through the harness, plus the arm a
display test is easiest to get wrong -- a BAD integrity counter must be drawn
as bad, which is planted in the pane's own state rather than by damaging the
store to provoke it.

And the harness defect this surfaced: the `open` gesture called Obsidian
commands without the plugin-id prefix, so `executeCommandById` returned false
and every pane "opened" without anything happening. It must fail loudly now.
"""

import os
import re
import time

import pytest

LIVE = os.environ.get("VERTISCOPE_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="needs VERTISCOPE_LIVE=1, the "
                                "sidecar and Obsidian")


@pytest.fixture(scope="module")
def live():
    from vertiscope.obsidian.live import Live
    got = Live()
    got.reload_plugin()
    opened = got.act("open", "browser").get("result") or {}
    assert opened.get("opened") == "browser", opened
    box = got.act("pipebox", "open").get("result") or {}
    assert box.get("expanded") is True, box
    time.sleep(3)
    return got


def _as_ms(text):
    """'4.51 s' -> 4510, '13 ms' -> 13, '1.3 ms' -> 1.3."""
    m = re.match(r"\s*([\d.]+)\s*(s|ms)\s*$", text or "")
    if not m:
        return None
    v = float(m.group(1))
    return v * 1000 if m.group(2) == "s" else v


def test_open_fails_loudly_for_a_pane_that_does_not_exist(live):
    got = live.act("open", "no-such-pane").get("result") or {}
    assert "error" in got, "open reported success for a pane that does not exist"


def test_the_readout_is_open_in_the_corner_box_and_no_pane_exists(live):
    ui = live.ui()
    box = ui.get("pipebox") or {}
    assert box.get("expanded") and box.get("asked_open"), box
    assert (ui.get("profile") or {}).get("e2e_shown") is not None,         "the corner box is open but the profile readout drew nothing"
    assert (ui.get("separate_panes") or {}).get("profile") == 0,         "a separate profile pane is open (G-76)"


def test_the_pane_shows_what_the_profiler_measured(live):
    summary = live.json_eval("JSON.stringify(window.__vertiscope.profile.summary())")
    e2e = ((summary or {}).get("stages") or {}).get("end_to_end")
    if not e2e:
        pytest.skip("no drain has reached the screen in this session yet")
    time.sleep(1.5)                                   # one redraw
    shown = (live.ui().get("profile") or {}).get("e2e_shown")
    shown_ms = _as_ms(shown)
    assert shown_ms is not None, "the pane shows no end-to-end: %r" % shown
    # The pane rounds for display; within 1% or 1 ms is the same number.
    assert abs(shown_ms - e2e["p50"]) <= max(1.0, 0.01 * e2e["p50"]), (
        "pane shows %s, profiler says %.1f ms" % (shown, e2e["p50"]))


def test_the_pane_follows_the_data_and_is_not_a_snapshot(live):
    """Reset the profiler; the pane must stop showing the old figure."""
    live.evaluate("window.__vertiscope.profile.reset()")
    deadline = time.time() + 4
    shown = None
    while time.time() < deadline:
        shown = (live.ui().get("profile") or {}).get("e2e_shown")
        if shown == "—":
            break
        time.sleep(0.5)
    assert shown == "—", (
        "after a reset the pane still shows %r -- it is displaying a copy, "
        "not the profiler" % shown)


def test_a_bad_integrity_counter_is_drawn_as_bad(live):
    """The planted arm. The pane is handed a health reading with 12,000
    empty-markdown chunks -- the defect that once hit 80% of the corpus --
    and must draw that row as bad. Planted in the pane's state, not the
    store, so the test never damages what it is checking."""
    got = live.evaluate(r"""(() => {
      const leaf = app.workspace.getLeavesOfType('vertiscope-browser-view')[0];
      const view = leaf && leaf.view && leaf.view.pipebox && leaf.view.pipebox.readout;
      if (!view) return 'no view';
      const real = view.health;
      view.health = Object.assign({}, real || {}, {chunks_empty_md: 12000});
      view.draw();
      const bad = Array.from(view.host.querySelectorAll(
        '.vertiscope-profile-integ.is-bad')).map(e => e.textContent);
      view.health = real;
      view.draw();
      return JSON.stringify(bad);
    })()""")
    assert got != "no view"
    assert "empty markdown" in (got or ""), (
        "12,000 empty chunks were not drawn as bad: %s" % got)
