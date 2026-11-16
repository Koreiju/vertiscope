"""`design_state.contradictions`: a row the document calls working whose own
live check last FAILED (2026-11-16: `D-40` read "Done" for three weeks over its
check's FAIL of 2026-10-24).

Non-vacuity: the planted contradiction is caught; the clean cases -- a pass, a
failing check on a row that does not claim to work, a check whose id only
LOOKS like the row's -- are not.
"""
from domvec.analytics.design_state import contradictions


def _row(tag, status):
    return {"tag": tag, "status": status}


def test_a_done_row_over_a_failing_check_is_caught():
    got = contradictions([_row("D-40", "done"), _row("G-6", "confirm")],
                         [{"id": "D-40", "pass": False, "when": "2026-10-24", "asks": "hover in ms"},
                          {"id": "G-6", "pass": False, "when": "2026-09-30", "asks": "nodes and edges"}])
    assert [c["tag"] for c in got] == ["D-40", "G-6"]
    assert got[0]["when"] == "2026-10-24"


def test_nothing_is_caught_where_nothing_disagrees():
    rows = [_row("G-1", "done"), _row("G-2", "partly"), _row("G-145", "partly")]
    live = [{"id": "G-1", "pass": True}, {"id": "G-2", "pass": False},
            {"id": "G-145p", "pass": False}, {"id": "G-145", "pass": False}]
    assert contradictions(rows, live) == []


def test_a_near_id_is_not_the_row():
    assert contradictions([_row("G-145", "done")], [{"id": "G-145p", "pass": False}]) == []
