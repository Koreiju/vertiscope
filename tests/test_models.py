"""G-262 / G-264 (PLUGIN_GOAL 186c, 186j): each model role parses its
natural output into its type, or says why not -- never coerced. The Triplex
fixture is the model's real output on its own model-card example
(2026-10-18, triplex-Q4_K_M.gguf on CPU)."""
from vertiscope.models import parse_chat, parse_triplex

TRIPLEX_RAW = '''  ```json
{
    "entities_and_triples": [
        "[1], CITY:San Francisco",
        "[2], LOCATION:City and County of San Francisco",
        "[3], COUNTRY:United States",
        "[6], NUMBER:808,437",
        "[1] AREA [2]",
        "[1] POPULATION [6]",
        "[8], LOCATION:California",
        "[8], CITY:California",
        "[1] POPULATION [99]",
        "[1] CAPITAL_OF [3]",
        "something else entirely"
    ]
}
```'''


def test_triplex_entities_and_triples_strictly():
    r = parse_triplex(TRIPLEX_RAW, ["POPULATION", "AREA"])
    assert r.ok, r.error
    v = r.value
    assert v["entities"]["1"] == {"type": "CITY", "name": "San Francisco"}
    assert {"s": "San Francisco", "p": "POPULATION", "o": "808,437"}.items() <= v["triples"][1].items()
    assert len(v["triples"]) == 2                                # AREA and POPULATION; the rest refused
    assert v["entities"]["8"]["type"] == "LOCATION"              # the first definition kept
    notes = " | ".join(r.notes)
    assert "defined again" in notes and "never defined" in notes and "not one asked for" in notes and "not an entity" in notes


def test_triplex_output_that_is_not_its_type_is_an_error_not_a_guess():
    for raw in ("I could not find anything.", '{"other": []}', "```json\n{broken\n```"):
        r = parse_triplex(raw)
        assert not r.ok and r.error and r.value is None


def test_chat_answer_is_prose_plus_code_with_its_kg():
    raw = "Here is a helper.\n\n```python\nimport os\npath = os.getcwd()\n```\n\nAnd a shell line:\n\n```bash\nls -la\n```\n"
    r = parse_chat(raw)
    assert r.ok
    py, sh = r.value["code"]
    assert py["lang"] == "python" and any(t["p"] == "IMPORTS" and t["o"] == "os" for t in py["kg"])
    assert sh["lang"] == "bash" and "kg" not in sh
    assert "Here is a helper." in r.value["prose"] and "```" not in r.value["prose"]


def test_triplex_reads_the_prose_not_the_link_targets():
    from vertiscope.models import plain
    md = "[Edit section: Lookup edit](/w/x)] A [radix tree](https://e.org/r) is ![img](a.png) a <https://x.org> **trie** `variant`."
    assert plain(md) == "A radix tree is a trie variant ."
