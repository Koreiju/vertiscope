"""The fold measures nothing.

Guards ``invariants.c2_fold_reads_no_layout``: every layout-reading call in
``sensor.js`` sits in a function that is allowed to measure -- the style
peripheral, the actuator, and the ``viewport`` variant's emission gate -- and
the fold itself reads none.

No browser. The regression this catches is one line of source, so it is caught
in the source, the same way ``a1`` and ``c1`` are.
"""

from vertiscope import invariants as inv


def test_fold_reads_no_layout():
    assert inv.c2_fold_reads_no_layout() == []


def test_a_layout_read_in_the_fold_is_reported():
    """Non-vacuity, the way that matters: plant the exact regression."""
    planted = (
        "  function fold(node) {\n"
        "    var r = node.getBoundingClientRect();\n"
        "    return r;\n"
        "  }\n"
    )
    violations = inv.c2_fold_reads_no_layout(planted)
    assert violations, "a getBoundingClientRect inside fold went unreported"
    assert any("fold" in v for v in violations)


def test_a_source_with_no_layout_calls_is_reported():
    """A pattern that matches nothing must not read as a clean bill."""
    violations = inv.c2_fold_reads_no_layout("  function fold(node) {}\n")
    assert violations
    assert any("no layout call found" in v for v in violations)


def test_the_peripheral_is_allowed_to_measure():
    """`styles` reading geometry is the design, not a violation."""
    allowed = (
        "  function styles(paths) {\n"
        "    var r = el.getBoundingClientRect();\n"
        "  }\n"
    )
    assert inv.c2_fold_reads_no_layout(allowed) == []
