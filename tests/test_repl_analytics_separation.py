"""The REPL is a browser; the analytics measure it. Neither imports the other.

`vertiscope/repl/app.py` carried eight class-level catalogues -- `AXES`, `LOSSY`,
`REGROUPING`, `READDRESSING`, `OVERLAPPING`, `TARGETS`, `QUERIES`,
`GROUND_TRUTH`, 109 lines -- naming a design space and a benchmark corpus.
Every one was defined exactly once and referenced nowhere: residue from
removing the `compare` / `variant` / `sweep` / `verify` commands, because
deleting a command and deleting its vocabulary are two edits and only the
first is obvious.

The constraint that analytics live in their own package, writing their own
artifacts, was already written down. It was not holding, and nothing noticed,
because a constraint with no check is a preference.

`c4` asserts the import boundary rather than the vocabulary. The boundary is
what the constraint is about and it is decidable; a word list would fail on any
comment that mentions a mechanism, and the REPL has to be able to describe what
it does. What it must not do is depend.

Half of these tests plant violations. An invariant only tested on clean source
is a check that certifies rather than checks -- and this project has shipped
that shape before: detection rates structurally incapable of being non-zero, a
composed-tree walk that never composed, all green.
"""

from vertiscope.invariants import c4_repl_and_analytics_stay_apart as c4


# --- the real tree ----------------------------------------------------------


def test_the_packages_are_separate_on_disk():
    assert c4() == []


# --- what it must catch -----------------------------------------------------


def test_a_relative_import_of_analytics_from_the_repl_is_caught():
    out = c4({"repl/app.py": "from ..analytics import drift\n"})
    assert out and "analytics" in out[0]


def test_an_absolute_import_of_analytics_from_the_repl_is_caught():
    out = c4({"repl/app.py": "import vertiscope.analytics.drift\n"})
    assert out and "analytics" in out[0]


def test_importing_the_subpackage_by_name_is_caught():
    """`from . import analytics` names no module in `node.module` at all."""
    out = c4({"repl/nav.py": "from . import analytics\n"})
    assert out and "analytics" in out[0]


def test_the_boundary_is_enforced_in_both_directions():
    """An analytics module reaching into the REPL is measuring the instrument
    instead of the page -- the same mistake, mirrored."""
    out = c4({"analytics/drift.py": "from ..repl.app import App\n"})
    assert out and "repl" in out[0]


def test_every_offending_file_is_named_not_just_the_first():
    out = c4({"repl/app.py": "from ..analytics import drift\n",
              "repl/nav.py": "import vertiscope.analytics\n",
              "analytics/run.py": "from ..repl import app\n"})
    assert len(out) == 3


def test_the_line_is_reported_so_the_finding_is_actionable():
    out = c4({"repl/app.py": "import os\nimport sys\n"
                             "from ..analytics import drift\n"})
    assert out and ":3" in out[0]


# --- what it must not catch -------------------------------------------------


def test_talking_about_analytics_is_not_depending_on_them():
    """The REPL has to be able to say what it is and is not for."""
    assert c4({"repl/app.py":
               "# analytics live in vertiscope/analytics, not here\n"
               "HELP = 'this is not the analytics tool'\n"
               "from ..trie import AddressTrie\n"}) == []


def test_a_module_importing_anything_else_is_left_alone():
    assert c4({"repl/app.py": "from ..sensing import Sensor\n"
                              "from ..markdown import render_trie\n",
               "analytics/drift.py": "from ..stream import StreamingScan\n"}) == []


def test_a_package_outside_the_boundary_is_not_policed():
    """`sensing` may import whatever it likes; this rule is about two
    packages, and a check that quietly widened its own scope would be a
    different rule than the one documented."""
    assert c4({"sensing.py": "from .analytics import drift\n"}) == []


def test_a_file_that_will_not_parse_is_reported_rather_than_passed():
    out = c4({"repl/app.py": "def broken(:\n"})
    assert out and "parse" in out[0]
