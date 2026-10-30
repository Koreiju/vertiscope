"""G-277: the slate grammar round-trips -- the mothership's dialect over tabs
and newlines (docs/RESERVOIR_DESIGN.md §3.1, §8.1).

The goldens are the mothership's own examples (its verbatim N.7, N.9, M.3,
O.20). Planted: a parser that splits keys on spaces -- the way a colon- or
space-leaning parse reads a slate -- fails the names-with-spaces identity.
"""

from domvec.slate import Field, parse_slate, print_slate, refs

DUCKDUCKGO = "\n".join([
    "DuckDuckGo",
    "\tscanner",
    "\t\turl\t{duckduckgo url}",
    "\t\tdom\t{scan for duckduckgo url}",
    "duckduckgo url\thttps://www.duckduckgo.com/",
    "scan for duckduckgo url",
    "\tsearch\t{}",
    "\t{paginate}",
    "\tchunk\t{chunk samples}",
])

WEBBROWSER = "\n".join([
    "self : WebBrowser",
    "\tNO_CHANGE_LIMIT : int = 3",
    "\tSETTLE_TIMEOUT : float = 0.25",
    "\tdriver : WebDriver = {driver}",
    "\tscanner : {FunctionOutPutType} = {scan}",
])


def test_print_and_parse_are_inverse_on_the_dialect():
    for text in (DUCKDUCKGO,):
        assert print_slate(parse_slate(text)) == text


def test_names_hold_spaces_and_a_tab_separates_the_value():
    fields = parse_slate(DUCKDUCKGO)
    names = [f.key for f in fields]
    assert names == ["DuckDuckGo", "duckduckgo url", "scan for duckduckgo url"]
    assert fields[1].value == "https://www.duckduckgo.com/"


def test_refs_are_the_only_markup_and_braces_mark_the_on_ramp():
    fields = parse_slate(DUCKDUCKGO)
    assert fields[0].refs() == ["duckduckgo url", "scan for duckduckgo url"]
    assert fields[2].refs() == ["", "paginate", "chunk samples"]       # `{}` is unbound
    assert refs("label {a} and {b}") == ["a", "b"]


def test_a_block_beneath_a_key_is_its_multiline_value():
    text = "prompt\n\tSummarise the page.\n\tKeep {style} in mind."
    f = parse_slate(text)[0]
    assert f.value == "Summarise the page.\nKeep {style} in mind." and not f.children
    assert print_slate([f]) == text
    assert f.refs() == ["style"]


def test_positional_children_keep_their_markers():
    text = "plan\n\t- {first}\n\t- {second}\n\t1. numbered"
    f = parse_slate(text)[0]
    assert [c.marker for c in f.children] == ["- ", "- ", "1. "]
    assert print_slate([f]) == text


def test_space_indented_text_parses_by_its_own_unit():
    text = "root\n    child\n        grandchild\tvalue"
    f = parse_slate(text)[0]
    assert f.children[0].key == "child" and f.children[0].children[0].value == "value"
    assert print_slate([f]) == "root\n\tchild\n\t\tgrandchild\tvalue"   # canonical: tabs


def test_api_objects_render_typed_and_round_trip():
    fields = parse_slate(WEBBROWSER, typed=True)
    self_ = fields[0]
    assert (self_.key, self_.type) == ("self", "WebBrowser")
    driver = self_.children[2]
    assert (driver.key, driver.type, driver.value) == ("driver", "WebDriver", "{driver}")
    assert print_slate(fields, typed=True) == WEBBROWSER
    # A user node renders type-stripped: the same record without its types.
    assert "WebDriver" not in print_slate(fields)


def test_planted_a_space_splitting_parse_breaks_the_names():
    """Non-vacuity: the identity above can fail. A parse that takes the first
    word as the key (as a space- or colon-leaning parser does) loses names."""
    def naive(text):
        out = []
        for line in text.split("\n"):
            body = line.lstrip("\t")
            k, _, v = body.partition(" ")
            out.append("\t" * (len(line) - len(body)) + k + ("\t" + v if v else ""))
        return "\n".join(out)
    assert naive(DUCKDUCKGO) != DUCKDUCKGO


def test_a_record_built_in_code_prints_as_the_dialect():
    rec = [Field("ego", children=[Field("view", "ego"), Field("throttle", "25"),
                                  Field("keys", "{keys}"), Field("plan", "{flight plan}")])]
    text = print_slate(rec)
    assert text == "ego\n\tview\tego\n\tthrottle\t25\n\tkeys\t{keys}\n\tplan\t{flight plan}"
    assert parse_slate(text) == rec
