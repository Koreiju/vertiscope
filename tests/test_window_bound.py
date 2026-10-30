"""`S-11` scored against the user's own bound (`G-86`, `markdown.LENIENCY`).

"If this is closer to 512 than 256 in the merge after the context limit, keep
the previous, otherwise include the merge as the final chunk": a run may pass
256 while it stays under 384. The window pass reports overs past 256 AND past
that bound; only the second is a cut that should have happened. Planted: the
pass's own oversize record must land past the bound.
"""

from domvec.analytics import window as W
from domvec.markdown import LENIENCY


def _rows(costs):
    # One word costs about one token; lines carry the cuttable flag.
    out = []
    for i, (n_words, lines) in enumerate(costs):
        md = "\n".join(" ".join("w%d" % k for k in range(n_words // max(1, lines))) for _ in range(lines))
        out.append(("c%d" % i, "https://t.test/p", md, lines, "", 1))
    return out


def test_the_bound_is_the_users_rule_and_only_past_it_counts(monkeypatch):
    assert int(256 * LENIENCY) == 384
    from domvec import tokens
    rows = _rows([(200, 4), (330, 6), (900, 9), (5000, 1)])
    costs = [tokens.budget_for(r[2], r[1]) for r in rows]
    monkeypatch.setattr(W, "_rows_from_sidecar", lambda base: rows)
    rep = W.measure_window("", window=256, sidecar="http://x")
    assert rep["lenient_bound"] == 384
    want_div = sum(1 for (c, (_w, l)) in zip(costs, [(200, 4), (330, 6), (900, 9), (5000, 1)]) if l > 1 and c > 384)
    assert rep["past_bound"]["divisible"] == want_div
    assert rep["past_bound"]["indivisible"] == (1 if costs[3] > 384 else 0)
    # Planted: the pass's own multi-line oversize record is caught past the bound.
    planted = W.measure_window("", window=256, sidecar="http://x", plant=True)
    assert planted["plant_caught"] and planted["past_bound"]["divisible"] == want_div + 1
