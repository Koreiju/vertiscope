"""G-205's one tool (`domvec.browse`), against a fake ranking -- each claim with its arm."""

import pytest

from domvec import browse

PAGES = {
    "https://en.wikipedia.org/wiki/Trie": ["/html/body/div[9]", "/html/body/div[10]", "/html/body/div[2]"],
    "https://en.wikipedia.org/wiki/Radix_tree": ["/html/body/p[1]"],
    "https://de.wikipedia.org/wiki/Trie": ["/html/body/p[1]"],
    "https://example.com/tries": ["/html/body/p[1]"],
    "https://unrelated.org/cats": ["/html/body/p[1]"],
}
SIM = [("https://en.wikipedia.org/wiki/Trie", "https://example.com/tries", 0.4)]


def _search(query, k, urls):
    hits = []
    for u, xs in PAGES.items():
        if urls is not None and u not in urls:
            continue
        for i, x in enumerate(xs):
            hits.append({"cid": "%s#%d" % (u, i), "url": u, "xpath": x, "preview": "", "score": 1.0 / (1 + len(hits))})
    return hits[:k]


def _session():
    return browse.Session(_search, lambda: (list(PAGES), SIM))


TRIE = "https://en.wikipedia.org/wiki/Trie"


def test_domain_widens_host_then_registrable_then_similar():
    a = _session().call(query="trie", scope="domain", of=TRIE, k=20)["artifact"]
    levels = {h["url"]: h["level"] for h in a["results"]}
    assert levels["https://en.wikipedia.org/wiki/Radix_tree"] == "host"
    assert levels["https://de.wikipedia.org/wiki/Trie"] == "domain"
    assert levels["https://example.com/tries"] == "similar"
    assert "https://unrelated.org/cats" not in levels        # never reached by any level


def test_every_level_contributes_even_when_the_host_alone_fills_k():
    # Live run 80: a four-page host filled k=30 and draft 1 never widened.
    a = _session().call(query="trie", scope="domain", of=TRIE, k=3)["artifact"]
    assert [h["level"] for h in a["results"]][:1] == ["host"]
    assert {h["level"] for h in a["results"]} == {"host", "domain", "similar"}


def test_planted_host_only_reaches_neither_wider_level():
    browse.PLANT_DOMAIN_HOST_ONLY[0] = True
    try:
        a = _session().call(query="trie", scope="domain", of=TRIE, k=20)["artifact"]
    finally:
        browse.PLANT_DOMAIN_HOST_ONLY[0] = False
    assert {h["level"] for h in a["results"]} == {"host"}


def test_page_scope_reads_in_document_order():
    a = _session().call(query="trie", scope="page", of=TRIE, k=10)["artifact"]
    assert [h["xpath"] for h in a["results"]] == ["/html/body/div[2]", "/html/body/div[9]", "/html/body/div[10]"]


def test_down_asks_the_cell_and_the_cell_streams_the_trace():
    s = _session()
    a = s.call(query="trie", scope="web")["artifact"]
    cid = a["results"][0]["cid"]
    got = s.call(down=cid)
    assert got["asks"] == [{"reveal": {"url": TRIE, "xpath": "/html/body/div[9]", "cid": cid}}]
    v = got["version"]
    assert s.observe(TRIE) is None                            # the same page: no step
    assert s.observe("https://en.wikipedia.org/wiki/Patricia") is not None
    trace = s._result(cid)["trace"]
    assert [t["by"] for t in trace] == ["down", "browser"]
    assert [c["move"] for c in s.since(v)["changes"]] == ["trace"]


def test_up_walks_toward_the_origin_and_stops_recording():
    s = _session()
    cid = s.call(query="trie")["artifact"]["results"][0]["cid"]
    s.call(down=cid)
    assert s.call(up=True)["artifact"]["cursor"] == {"at": "results"}
    # Outside a trace the reader's own browsing is not recorded.
    assert s.observe("https://elsewhere.org/") is None
    assert s.call(up=True)["artifact"]["cursor"] == {"at": "query"}


def test_act_is_asked_of_the_cell():
    s = _session()
    got = s.call(act={"address": "u|/html/body/input[1]|md|input|value", "value": "x"})
    assert got["asks"] == [{"act": {"address": "u|/html/body/input[1]|md|input|value", "value": "x"}}]


def test_one_move_per_call():
    with pytest.raises(ValueError):
        _session().call(query="trie", up=True)
    with pytest.raises(ValueError):
        _session().call(query="trie", scope="domain")          # domain needs `of`
