"""PLUGIN_GOAL 80: a code `{ref}` is a black box, unfolded one rank at a time
(`domvec/obsidian/blackbox.py`)."""

from domvec.obsidian import blackbox

SRC = '''
def top(a, b=2):
    """Adds them.

    More words."""
    return a + b


class Box:
    def open(self):
        pass

    class Inner:
        def deep(self, x):
            return x
'''


def test_a_module_shows_its_top_level_definitions_only():
    got = blackbox.unfold("code://repo/m.py", SRC)
    assert got["kind"] == "module"
    assert got["lines"] == ["def top\t{code://repo/m.py#top}", "class Box\t{code://repo/m.py#Box}"]


def test_each_rank_unfolds_the_next():
    box = blackbox.unfold("code://repo/m.py#Box", SRC)
    assert box["kind"] == "class"
    assert box["lines"] == ["def open\t{code://repo/m.py#Box.open}", "class Inner\t{code://repo/m.py#Box.Inner}"]
    inner = blackbox.unfold("code://repo/m.py#Box.Inner", SRC)
    assert inner["lines"] == ["def deep\t{code://repo/m.py#Box.Inner.deep}"]


def test_a_function_is_a_leaf_with_its_signature_and_first_doc_line():
    got = blackbox.unfold("code://repo/m.py#top", SRC)
    assert got["kind"] == "function"
    # Typed rows (DM 9.6.1): unannotated slots say `?`, to be inferred.
    assert got["lines"] == ["signature\ttop(a, b=2)", "a: ?", "b: ? = 2", "return: ?", "doc\tAdds them."]


def test_an_unknown_name_resolves_to_nothing():
    assert blackbox.unfold("code://repo/m.py#Nope", SRC) is None


def test_planted_flat_opens_everything_at_once():
    blackbox.PLANT_FLAT[0] = True
    try:
        got = blackbox.unfold("code://repo/m.py", SRC)
    finally:
        blackbox.PLANT_FLAT[0] = False
    assert len(got["lines"]) == 5            # top, Box, open, Inner, deep


TYPED = '''
class Base:
    pass


class Car(Base):
    wheels: int = 4

    def drive(self, km: float, *, fast: bool = False) -> str:
        return ""
'''


def test_typed_rows_name_their_types():
    car = blackbox.unfold("code://repo/t.py#Car", TYPED)
    assert car["lines"][:2] == ["super: Base", "wheels: int = 4"]
    drive = blackbox.unfold("code://repo/t.py#Car.drive", TYPED)
    assert drive["lines"][1:] == ["km: float", "fast: bool = False", "return: str"]


def test_planted_untyped_drops_the_type_rows():
    blackbox.PLANT_UNTYPED[0] = True
    try:
        drive = blackbox.unfold("code://repo/t.py#Car.drive", TYPED)
    finally:
        blackbox.PLANT_UNTYPED[0] = False
    assert drive["lines"] == ["signature" + chr(9) + "drive(self, km: float, *, fast: bool=False)"]
