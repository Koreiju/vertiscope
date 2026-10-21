"""G-233 (PLUGIN_GOAL 162): a web code block is ONE code artifact.

Live-gated (a real browser): ``VERTISCOPE_LIVE=1``. The fixture is a highlighted
``pre > code`` with token spans and a copy button beside it, as huggingface
draws a model card's sample. Claim: one unit at the ``pre``, holding the
code whole with its newlines. Planted ``plants.codespans``: the old walk,
which cut the block into its spans -- the check can fail.
"""
import os
import pathlib
import time

import pytest

LIVE = pytest.mark.skipif(not os.environ.get("VERTISCOPE_LIVE"),
                          reason="needs a real browser; set VERTISCOPE_LIVE=1")
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "code_block.html"


def _drain(planted: bool):
    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.sensing import Sensor
    url = FIXTURE.as_uri()
    with browser_session(load_config(), headless=True) as driver:
        driver.get(url)
        time.sleep(0.8)
        # Planted at BOOT: chunks are emitted and cached at the first fold.
        sensor = Sensor(driver, url, budget=200, variants={"codespans": planted})
        sensor.boot()
        time.sleep(0.6)
        return sensor.drain(0)


@LIVE
def test_a_code_block_is_one_unit_at_its_pre():
    units = [(a.xpath, v or "") for a, v in _drain(False).units]
    code = [(x, v) for x, v in units if "import json" in v]
    assert len(code) == 1, code
    xpath, value = code[0]
    assert "/pre" in xpath and "/code" not in xpath.split("/pre")[-1], xpath
    assert "def triplextract" in value and "\n" in value and "return message" in value
    assert not any("/span" in x for x, _ in units), "a highlighting span became its own unit"


@LIVE
def test_planted_the_old_walk_cuts_the_block_into_spans():
    units = [(a.xpath, v or "") for a, v in _drain(True).units]
    whole = [v for _, v in units if "import json" in v and "return message" in v]
    assert not whole, "the planted walk kept the block whole: this check cannot fail"
