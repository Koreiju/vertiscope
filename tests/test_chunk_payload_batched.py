"""A chunk payload's element lookups, batched into one query, answer exactly
what one query per element answered (2026-10-07: 0.36-2.0 s per panel on the
working store came from one `addresses_at` scan per element)."""

import pathlib

from domvec.obsidian.sidecar import chunk_payload
from domvec.workspace import Workspace

FIX = pathlib.Path(__file__).parent / "fixtures" / "panel_act.html"


def test_batched_lookups_give_the_same_payload(tmp_path):
    with Workspace(tmp_path) as ws:
        url = "http://127.0.0.1/panel_act.html"
        ws.index_html(FIX.read_text(encoding="utf-8"), url)
        cids = [c.cid for c in ws.store.chunks(url)]
        assert cids
        batched = [chunk_payload(ws, c) for c in cids]
        many = ws.store.addresses_at_many
        calls = {"n": 0}
        try:
            ws.store.addresses_at_many = None          # the old path: one query per element
            orig = ws.store.addresses_at

            def counted(*a, **k):
                calls["n"] += 1
                return orig(*a, **k)
            ws.store.addresses_at = counted
            single = [chunk_payload(ws, c) for c in cids]
        finally:
            ws.store.addresses_at_many = many
        assert batched == single
        # The planted comparison does what it claims: per-element queries ran.
        assert calls["n"] > 1
