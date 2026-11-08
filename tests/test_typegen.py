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
