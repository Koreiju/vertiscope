"""`search(query, db, duckduckgo, k)` in the kernel (G-288, RESERVOIR_DESIGN §6b).

The function runs in the kernel's own namespace, so it is tested there: the
bootstrap exec'd into a fresh dict, `Database.search` stubbed (the route is
G-279's and is checked live), and the asks drained exactly as the sidecar
drains them after a cell.
"""

from domvec.obsidian import kernel_objects as ko


def _kernel():
    ns: dict = {}
    exec(ko.boot("http://127.0.0.1:1"), ns)
    ns["Database"].search = lambda q, k=5, where="": [{"cid": "c%d" % i, "url": "u", "text": q} for i in range(k)]
    return ns


def _drain(ns):
    return ko.parse_asks({"value": repr(eval(ko.DRAIN, ns))})


def test_db_only_asks_nothing_of_the_app():
    ns = _kernel()
    got = ns["search"]("radix tree", k=3)
    assert [h["cid"] for h in got] == ["c0", "c1", "c2"]
    assert all(h["source"] == "db" for h in got)
    assert _drain(ns) == []


def test_duckduckgo_asks_the_browser_cell_and_never_fetches():
    ns = _kernel()
    got = ns["search"]("radix tree", db=False, duckduckgo=True)
    assert len(got) == 1 and got[0]["source"] == "duckduckgo" and got[0]["pending"]
    assert got[0]["url"] == "https://duckduckgo.com/?q=radix%20tree"
    assert _drain(ns) == [{"web": "radix tree"}]
    # Drained once: a second drain is empty, so one call is one search.
    assert _drain(ns) == []


def test_both_keep_the_db_ranking_and_ask_once():
    ns = _kernel()
    got = ns["search"]("q", db=True, duckduckgo=True, k=2)
    assert [h["source"] for h in got] == ["db", "db", "duckduckgo"]
    assert _drain(ns) == [{"web": "q"}]


def test_boot_is_idempotent_and_keeps_pending_asks():
    ns = _kernel()
    ns["search"]("a", db=False, duckduckgo=True)
    exec(ko.boot("http://127.0.0.1:1"), ns)        # the next cell's bootstrap
    assert _drain(ns) == [{"web": "a"}]


def test_parse_asks_refuses_what_is_not_a_drain():
    assert ko.parse_asks(None) == []
    assert ko.parse_asks({"value": None}) == []
    assert ko.parse_asks({"value": "42"}) == []
    assert ko.parse_asks({"value": repr('[{"web": "x"}, 3]')}) == [{"web": "x"}]
