"""Drawing a ```tool cell is not a call (Item 201: "exiting the ``` fields would
then produce the call"). Seen 2026-11-28: re-rendering a cell on the 2D editor
pushed a stack frame each time (5/5 after a few reloads)."""
from domvec import tool_cells

SRC = '{"search": {"search": "trie"}}'


def _total(r):
    return r["stack"]["total"]


def test_peek_leaves_the_stack_alone():
    tool_cells.reset_stacks(); tool_cells.PLANT_PEEK_PUSHES[0] = False
    first = tool_cells.execute({"session": "pk", "source": SRC})                  # the call
    assert _total(first) == 1
    for _ in range(3):
        drawn = tool_cells.execute({"session": "pk", "source": '{"search": {"search": "other"}}', "peek": True})
        assert _total(drawn) == 1
    called = tool_cells.execute({"session": "pk", "source": '{"search": {"search": "other"}}'})
    assert _total(called) == 2


def test_planted_peek_pushes():
    tool_cells.reset_stacks(); tool_cells.PLANT_PEEK_PUSHES[0] = True
    try:
        tool_cells.execute({"session": "pk2", "source": SRC})
        r = tool_cells.execute({"session": "pk2", "source": '{"search": {"search": "other"}}', "peek": True})
        assert _total(r) == 2
    finally:
        tool_cells.PLANT_PEEK_PUSHES[0] = False
