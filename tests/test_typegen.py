"""T-15: pydantic types from trie-path patterns, with the planted arm."""
from domvec import typegen as T

ROWS = [
    ("https://a.example/", "/html/body/main/article[1]/h2", "text", "First"),
    ("https://a.example/", "/html/body/main/article[1]/span[1]", "text", "12"),
    ("https://a.example/", "/html/body/main/article[1]/a", "href", "https://a.example/1"),
    ("https://a.example/", "/html/body/main/article[2]/h2", "text", "Second"),
    ("https://a.example/", "/html/body/main/article[2]/span[3]", "text", "7"),
    ("https://a.example/", "/html/body/main/article[2]/a", "href", "https://a.example/2"),
    ("https://b.example/", "/html/body/main/article[1]/h2", "text", "Other"),
    ("https://b.example/", "/html/body/main/article[1]/span[2]", "text", "3"),
    ("https://b.example/", "/html/body/nav/a", "href", "https://b.example/x"),
]


def test_instances_span_pages_and_fields_generalise():
    m = T.model(ROWS, "/html/body/main/article[*]", "post")
    assert m["instances"] == 3 and m["pages"] == 2
    src = m["source"]
    assert "class Post(BaseModel):" in src
    assert "    h2_text: str" in src
    assert "    span_text: int" in src            # [1], [3], [2] are ONE field
    assert "    a_href: Optional[HttpUrl] = None" in src
    assert "nav" not in src                        # outside the pattern


def test_planted_no_generalise_splits_the_field():
    T.PLANT_NO_GENERALISE[0] = True
    try:
        src = T.model(ROWS, "/html/body/main/article[*]")["source"]
    finally:
        T.PLANT_NO_GENERALISE[0] = False
    assert "span_1_text" in src and "span_3_text" in src and "    span_text" not in src


def test_prefix_and_regex():
    assert T.prefix_of("/html/body/main/article[*]/h2") == "/html/body/main/"
    rx = T.pattern_regex("/html/body/main/article[*]")
    assert rx.match("/html/body/main/article[4]/p")
    assert not rx.match("/html/body/main/articles[4]")


# --- G-388: patterns mined across pages, strict types ----------------------

import random

import pytest
from pydantic import ValidationError


def _corpus(pages=3, items=4):
    """A product list on every page, a list repeated on ONE page only, and a
    `div[*]` repeat on every page whose members share nothing."""
    rows = []
    for p in range(pages):
        url = "https://shop.example/c/%d" % p
        for i in range(1, items + 1):
            root = "/html/body/main/ul/li[%d]" % i
            rows += [(url, root + "/a", "href", "https://shop.example/p/%d%d" % (p, i)),
                     (url, root + "/a/text()[1]", "text", "Item %d" % i),
                     (url, root + "/span[2]", "text", str(10 * i + p))]
        for i in range(1, 4):                         # unlike siblings
            rows.append((url, "/html/body/div[%d]/%s" % (i, ["nav", "form", "img"][i - 1]), "text", "x"))
    for i in range(1, 6):                             # one page only
        rows += [("https://shop.example/c/0", "/html/body/aside/ol/li[%d]/b" % i, "text", "n%d" % i),
                 ("https://shop.example/c/0", "/html/body/aside/ol/li[%d]/i" % i, "text", "m%d" % i)]
    return rows


def test_mine_recovers_the_cross_page_record():
    got = {r["pattern"]: r for r in T.mine(_corpus())}
    li = got["/html/body/main/ul/li[*]"]
    assert li["instances"] == 12 and li["pages"] == 3
    assert set(li["fields"]) == {"a_href", "a_text_text", "span_text"} or len(li["fields"]) == 3
    assert "/html/body/aside/ol/li[*]" not in got      # single page: a repeat, not a type
    assert "/html/body/div[*]" not in got              # no shared shape


def test_planted_no_shape_admits_what_the_shape_test_refuses():
    T.PLANT_NO_SHAPE[0] = True
    try:
        got = {r["pattern"] for r in T.mine(_corpus())}
    finally:
        T.PLANT_NO_SHAPE[0] = False
    assert "/html/body/aside/ol/li[*]" in got and "/html/body/div[*]" in got


def test_null_arm_shapeless_corpus_mines_nothing():
    """Same roots, same pages, same counts -- every field a fresh name."""
    rnd = random.Random(7)
    rows = [(u, x.rsplit("/", 1)[0] + "/t%06d" % rnd.randrange(10 ** 6), a, v)
            if "/li[" in x else (u, x, a, v) for u, x, a, v in _corpus()]
    assert T.mine(rows) == []


def test_mined_pattern_makes_a_strict_type_agents_can_use():
    rows = _corpus()
    pat = T.mine(rows)[0]["pattern"]
    out = T.objects(rows, pat, "product")
    assert len(out["objects"]) == 12 and not out["rejected"]
    cls = out["cls"]
    assert "strict=True" in out["model"]["source"]
    ints = [f for f, t in out["model"]["types"].items() if t == "int"]
    assert ints, out["model"]["types"]
    ok = out["objects"][0]["object"].model_dump()
    with pytest.raises(ValidationError):              # strict: a string is not an int
        cls.model_validate({**ok, ints[0]: str(ok[ints[0]])})
    with pytest.raises(ValidationError):              # extra=forbid
        cls.model_validate({**ok, "invented": 1})


def test_accessor_offsets_are_one_field_and_the_plant_splits_them():
    """Live defect: `text()[1196]` made one paragraph 400 fields."""
    rows = [("https://a.example/", "/html/body/section/article[%d]/p" % i, "text()[%d]|text.visible/p" % (i * 7), "t")
            for i in range(1, 5)] + \
           [("https://b.example/", "/html/body/section/article[%d]/p" % i, "text()[%d]|text.visible/p" % (i * 9), "t")
            for i in range(1, 5)]
    m = T.model(rows, "/html/body/section/article[*]")
    assert list(m["types"]) == ["p_text"] and m["required"] == 1
    T.PLANT_NO_GENERALISE[0] = True
    try:
        assert len(T.model(rows, "/html/body/section/article[*]")["types"]) > 1
    finally:
        T.PLANT_NO_GENERALISE[0] = False


def test_piece_marks_are_one_field():
    """Live defect: a paragraph split into pieces (`text()[0]~1196`) became
    a field per piece."""
    rows = []
    for u in ("https://a.example/", "https://b.example/"):
        for i in range(1, 4):
            x = "/html/body/section/article[%d]/p/text()[1]" % i
            rows += [(u, x, "text()[0]|text.visible/p", "head"),
                     (u, x, "text()[0]~1196|text.visible/p", "tail"),
                     (u, x, "text()[0]|text.visible/p~2400", "tail2")]
    assert list(T.model(rows, "/html/body/section/article[*]")["types"]) == ["p_text_text"]


def test_url_offsets_are_one_field_apart_from_the_text():
    """Live: `text()@1196` (a URL at offset 1196 of the text) made a field
    per offset. One field, distinct from the text it sits in; the plant
    splits it again."""
    rows = []
    for u in ("https://a.example/", "https://b.example/"):
        for i in range(1, 4):
            x = "/html/body/section/article[%d]/p/text()[1]" % i
            rows += [(u, x, "text()[0]|text.visible/paragraph", "words"),
                     (u, x, "text()@%d|text.visible/paragraph" % (1190 + i), "https://x.example/%d" % i)]
    types = T.model(rows, "/html/body/section/article[*]")["types"]
    assert sorted(types) == ["p_text_text", "p_text_text_url"] and types["p_text_text_url"] == "HttpUrl"
    T.PLANT_NO_GENERALISE[0] = True
    try:
        assert len(T.model(rows, "/html/body/section/article[*]")["types"]) == 4
    finally:
        T.PLANT_NO_GENERALISE[0] = False
