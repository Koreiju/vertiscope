"""A chunk payload's element lookups, batched into one query, answer exactly
what one query per element answered (2026-10-07: 0.36-2.0 s per panel on the
working store came from one `addresses_at` scan per element)."""

import pathlib

from vertiscope.obsidian import sidecar
from vertiscope.obsidian.sidecar import chunk_payload
from vertiscope.workspace import Workspace

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
            sidecar._PLANT_CONTROL_SCAN[0] = True
            orig = ws.store.addresses_at

            def counted(*a, **k):
                calls["n"] += 1
                return orig(*a, **k)
            ws.store.addresses_at = counted
            single = [chunk_payload(ws, c) for c in cids]
        finally:
            ws.store.addresses_at_many = many
            sidecar._PLANT_CONTROL_SCAN[0] = False
        # Timings differ run to run; the payload itself must not.
        strip = lambda ps: [{k: v for k, v in p.items() if k != "_ms"} for p in ps]  # noqa: E731
        assert strip(batched) == strip(single)
        # The planted comparison does what it claims: per-element queries ran.
        assert calls["n"] > 1
