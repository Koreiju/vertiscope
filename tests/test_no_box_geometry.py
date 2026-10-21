"""Geometry for elements that draw text without generating a box.

`display: contents` generates no box by definition -- its children lay out in
its parent's flow -- so `getBoundingClientRect()` returns 0x0 while the text
is on the screen. It is the UA default for `<slot>`, so this is the ordinary
shape of a web component.

The style peripheral used to read "no rect" as "not visible", and the
wireframe drops a unit whose owner has no visible box, so every such run was
discarded from the drawing. Measuring a range over the element's own contents
gives what was actually laid out.

Live-gated: geometry is what is being tested, and only a browser has it.
"""

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "no_box_geometry.html"

pytestmark = pytest.mark.skipif(
    os.environ.get("VERTISCOPE_LIVE") != "1",
    reason="needs a browser; set VERTISCOPE_LIVE=1")


@pytest.fixture(scope="module")
def measured():
    import time

    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.sensing import Sensor

    url = FIXTURE.as_uri()
    with browser_session(load_config()) as driver:
        driver.get(url)
        time.sleep(0.4)
        sensor = Sensor(driver, url, budget=1200)
        sensor.boot()
        time.sleep(0.3)
        sensor.drain(0)

        def boxes(paths):
            payload = sensor.styles(
                [type("A", (), {"xpath": p})() for p in paths])
            from vertiscope.style import StyleMap
            smap = StyleMap()
            smap.absorb(paths, payload)
            return {p: smap.get(p) for p in paths}

        yield boxes


def test_display_contents_element_is_visible_and_measured(measured):
    """claim: an element with no box of its own still draws its text."""
    path = "/html/body/div"
    box = measured([path])[path]
    assert box is not None
    assert box.visible, "display:contents read as not visible"
    assert box.w > 0 and box.h > 0, "no usable geometry for a drawn run"


def test_a_genuinely_hidden_element_stays_hidden(measured):
    """The fix must not admit what the page does not draw.

    Without this the change would be indistinguishable from deleting the
    visibility test.
    """
    paths = ["/html/body/div[3]", "/html/body/div[4]"]
    boxes = measured(paths)
    for path in paths:
        box = boxes[path]
        assert box is not None
        assert not box.visible, f"{path} is hidden and measured as visible"


def test_an_ordinary_element_is_unaffected(measured):
    path = "/html/body/div[5]"
    box = measured([path])[path]
    assert box is not None and box.visible and box.w > 0
