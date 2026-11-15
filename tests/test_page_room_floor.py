"""A page's copy drawn on top of it must not crush both clouds to a point.

G-94 (2026-11-15): Radix_tree's 40 chunks and its page within 0.045 units;
every check-created `?d35=` / `?g80=` / `?d37=` copy of it under 0.5, against
a median page spread of 4.2. `_place_chunks` scales a page's chunks into
NEIGHBOURHOOD x the distance to its nearest OTHER page, and a copy -- the same
content under a query string -- is fitted where the page is, so that distance
was ~0. The restart's fit with the copies purged read 2.08 at a room of 7.3:
the cap, not the fit. `_rooms` floors the distance at a share of the cloud's
median page spacing.

Planted `PLANT_ROOM_RAW_NEAREST`: the raw nearest distance, the collapse.
"""

import numpy as np

from domvec.obsidian.projector import PageProjector

from test_page_projector_default import _fit, _rows

COPY = "https://p0.test/?d36=fixture"


def _with_copy(seed=0):
    rows = _rows(seed=seed, spread=2.0)
    rng = np.random.default_rng(seed + 7)
    extra = []
    for cid, url, v in rows:
        if url == "https://p0.test/":
            w = np.asarray(v, dtype=np.float32) + rng.normal(size=len(v)).astype(np.float32) * 1e-3
            extra.append(("copy_" + cid, COPY, w.tolist()))
    return rows + extra


def _spread(proj, url):
    P = np.asarray([proj.pos[c] for c, u in proj.url_of.items() if u == url and c in proj.pos])
    return float(np.linalg.norm(P - P.mean(0), axis=1).mean())


def _on_top(proj, gap=0.05):
    """The copy fitted ON the page, as the live store had it: a synthetic
    15-page fit separates two identical pages (74 units here), the live
    1,000-page stream did not. The chunks are then placed as every writer
    places them, through `_place_chunks`."""
    here = np.asarray(proj.page_pos["https://p0.test/"], dtype=np.float64)
    proj.page_pos[COPY] = [float(x) for x in here + gap]
    proj.page_scale.clear()
    vec = {c: proj.vec[c] for c, u in proj.url_of.items()
           if u in ("https://p0.test/", COPY) and c in proj.vec}
    pos, _hsv = proj._place_chunks(proj.projection, vec)
    proj.pos.update(pos)
    return proj


def _readings(proj):
    others = [u for u in proj.page_pos if u not in ("https://p0.test/", COPY)]
    med = float(np.median([_spread(proj, u) for u in others]))
    d = float(np.linalg.norm(np.asarray(proj.page_pos[COPY]) - np.asarray(proj.page_pos["https://p0.test/"])))
    return _spread(proj, "https://p0.test/"), _spread(proj, COPY), med, d


def _baseline():
    # The same rows, the copy where the fit put it (74 units off): the
    # spread page 0 has when nothing sits on top of it.
    return _readings(_fit(_with_copy()))[0]


# Measured (2026-11-15): baseline 17.3; copy on top 4.17 with the floor,
# 0.0077 planted -- the synthetic twin of Radix_tree's 0.045.
def test_a_copy_on_top_leaves_both_clouds_their_spread():
    base = _baseline()
    page, copy, med, d = _readings(_on_top(_fit(_with_copy())))
    assert d < 1.0, d
    assert page > 0.1 * base and copy > 0.1 * base, (page, copy, base)


def test_planted_raw_nearest_crushes_the_page_and_its_copy(monkeypatch):
    monkeypatch.setattr(PageProjector, "PLANT_ROOM_RAW_NEAREST", [True])
    page, copy, med, d = _readings(_on_top(_fit(_with_copy())))
    base = _baseline()
    assert d < 1.0, d
    assert page < 0.01 * base and copy < 0.01 * base, (page, copy, base)


def test_a_page_without_a_copy_keeps_its_old_room():
    # The floor binds only below the cloud's own spacing: every page of the
    # clean corpus gets exactly the room the nearest-page rule gave it.
    proj = _fit(_rows(spread=2.0))
    rooms = proj._rooms(proj.page_pos, list(proj.page_pos))
    P = np.asarray([proj.page_pos[u] for u in proj.page_pos])
    for i, u in enumerate(proj.page_pos):
        d = np.linalg.norm(P - P[i], axis=1)
        raw = float(d[d > 1e-9].min()) * PageProjector.NEIGHBOURHOOD
        assert abs(rooms[u] - raw) < 1e-9 or rooms[u] > raw, (u, rooms[u], raw)
    floored = sum(1 for i, u in enumerate(proj.page_pos)
                  if rooms[u] > float(np.sort(np.linalg.norm(P - P[i], axis=1))[1]) * PageProjector.NEIGHBOURHOOD + 1e-9)
    assert floored <= 1, floored
