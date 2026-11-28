"""The search toolspace renders a store hit's preview TEXT, never the method object.

Seen live 2026-11-28 on the 2D editor: a chat reply's ```tool search printed
"<bound method Hit.preview of Hit(...)>" for every hit, because the store's
hits carry `preview` as a method (retrieve.Hit, search.Hit)."""
from domvec import tool_cells


class _Hit:
    def __init__(self, cid, url, text):
        self.cid, self.url, self.text, self.score = cid, url, text, 0.5

    def preview(self, width=160):
        return "PREVIEW " + self.text[:width]


class _Workspace:
    def search(self, q, k=8):
        return [_Hit("c1", "https://example.org/a", "a patricia trie keyed by address")]


def _run():
    tool_cells.reset_stacks()
    tool_cells.PLANT_NO_TOOL_CELL[0] = False
    return tool_cells.execute({"session": "t-hits", "source": '{"search": {"search": "patricia trie"}}'},
                              workspace=_Workspace())


def test_search_hit_preview_is_called_not_printed():
    text = str(_run())
    assert "<bound method" not in text
    assert "PREVIEW a patricia trie keyed by address" in text


def test_detector_catches_the_method_object():
    # Non-vacuity: the detector above flags the defect's own output.
    assert "<bound method" in str({"title": str(_Hit("c", "u", "t").preview)})
