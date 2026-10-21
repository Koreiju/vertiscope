"""PLUGIN_GOAL 110: a page's local refit moves nothing already placed.

The refit's new chunks are laid onto the old fit's frame; the old chunks keep
their places exactly. Planted: `plant_local_jumble` -- the refit's own
coordinates for every chunk, which moves them all.
"""

import numpy as np

from vertiscope.obsidian.projector import _keep_placed


def _rot(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _fits(seed=0, n_old=40, n_new=25):
    rng = np.random.default_rng(seed)
    truth = rng.normal(size=(n_old + n_new, 3))
    old_cids = ["c%03d" % i for i in range(n_old)]
    old = {"index": {c: i for i, c in enumerate(old_cids)}, "coords": truth[:n_old].copy()}
    # The refit: the same structure in another frame (rotated, scaled,
    # shifted), with a little of UMAP's own noise.
    cids = ["c%03d" % i for i in range(n_old + n_new)]
    new = (truth @ _rot(1.1)) * 2.7 + np.array([5.0, -3.0, 1.0])
    new = new + rng.normal(scale=0.01, size=new.shape)
    return cids, new, old, truth


def test_placed_chunks_keep_their_place_exactly():
    cids, new, old, _truth = _fits()
    out, kept = _keep_placed(cids, new, old)
    assert kept == 40
    for c, j in old["index"].items():
        assert np.allclose(out[cids.index(c)], old["coords"][j])


def test_new_chunks_land_in_the_old_frame():
    cids, new, old, truth = _fits()
    out, _ = _keep_placed(cids, new, old)
    # The 25 new chunks sit where the structure puts them in the OLD frame.
    err = np.linalg.norm(out[40:] - truth[40:], axis=1)
    assert float(err.max()) < 0.05, err.max()


def test_planted_refit_moves_everything():
    # The planted arm is the refit's own coordinates: every placed chunk moves.
    cids, new, old, _truth = _fits()
    moved = sum(1 for c, j in old["index"].items()
                if np.linalg.norm(new[cids.index(c)] - old["coords"][j]) > 0.25)
    assert moved == 40
    out, _ = _keep_placed(cids, new, old)
    moved_kept = sum(1 for c, j in old["index"].items()
                     if np.linalg.norm(out[cids.index(c)] - old["coords"][j]) > 0.25)
    assert moved_kept == 0


def test_no_shared_chunks_is_unchanged():
    cids, new, _old, _ = _fits()
    out, kept = _keep_placed(cids, new, {"index": {}, "coords": np.zeros((0, 3))})
    assert kept == 0 and np.allclose(out, new)
