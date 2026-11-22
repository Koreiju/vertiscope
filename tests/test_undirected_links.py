"""G-383: graph-form links are drawn undirected -- no arrowheads anywhere (mortegon UR O.16;
PLUGIN_GOAL 170 b). The dataflow's direction is computed (`dataflow.py`) and never drawn.

A source guard over the plugin: the constructs that draw a direction in the
libraries the plugin uses (force-graph's directional arrows and particles, an
SVG marker, three.js arrow/cone helpers). Planted arm: the guard must fire on
a source that has one.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "obsidian-plugin" / "src"
DRAWS_DIRECTION = re.compile(
    r"linkDirectionalArrow|linkDirectionalParticles|marker-end|markerEnd|ArrowHelper|arrowhead", re.I)


def offenders(files):
    out = []
    for f in files:
        text = Path(f).read_bytes().decode("utf-8", "replace")
        for n, line in enumerate(text.split("\n"), 1):
            if DRAWS_DIRECTION.search(line) and not line.lstrip().startswith(("//", "*")):
                out.append("%s:%d" % (Path(f).name, n))
    return out


def test_no_link_in_the_plugin_draws_a_direction():
    assert offenders(sorted(SRC.glob("*.ts"))) == []


def test_planted_arrow_is_caught(tmp_path):
    f = tmp_path / "planted.ts"
    f.write_text("graph.linkDirectionalArrowLength(4);\n// arrowhead in a comment is fine\n", encoding="utf-8")
    assert offenders([f]) == ["planted.ts:1"]
