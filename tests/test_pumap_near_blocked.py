"""Landmark selection in blocks: the same answer, a bounded peak.

`update_subset` chose its landmarks with ONE cdist of the active rows against
every held row; against a whole store (~85k held) a page update allocated
5.1 GB on the 8 GB card the chat model shares, and chat fell from 41.8 to
0.52 tokens/s (PLUGIN_GOAL 159, measured 2026-11-14). Blocked it must pick
EXACTLY the same rows; on CUDA its peak must be a fraction of the whole one.
Planted `DOMVEC_PLANT_WHOLE_CDIST=1` is the one-block selection.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
import domvec.obsidian.pumap as pm


def _pick(monkeypatch, planted, dev, Xa, Xh, block=256):
    monkeypatch.setattr(pm, "NEAR_BLOCK", block)
    if planted:
        monkeypatch.setenv("DOMVEC_PLANT_WHOLE_CDIST", "1")
    else:
        monkeypatch.delenv("DOMVEC_PLANT_WHOLE_CDIST", raising=False)
    A = torch.as_tensor(Xa, device=dev); H = torch.as_tensor(Xh, device=dev)
    if dev.type == "cuda":
        torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        base = torch.cuda.memory_allocated()
    near = pm._near_held(A, H, 8, 768).cpu().numpy()
    peak = (torch.cuda.max_memory_allocated() - base) / 1048576 if dev.type == "cuda" else None
    return near, peak


def test_blocked_selection_is_identical_and_its_peak_is_bounded(monkeypatch):
    rng = np.random.default_rng(0)
    Xa = rng.standard_normal((3000, 64)).astype(np.float32)
    Xh = rng.standard_normal((20000, 64)).astype(np.float32)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    blocked, p_blocked = _pick(monkeypatch, False, dev, Xa, Xh)
    whole, p_whole = _pick(monkeypatch, True, dev, Xa, Xh)
    assert len(blocked) == 768
    assert np.array_equal(np.sort(blocked), np.sort(whole))
    if dev.type == "cuda":
        # whole: 3000 x 20000 floats = 229 MB (plus top-k's copy); blocked: 256 rows a time.
        assert p_whole > 200 and p_blocked < p_whole / 4, (p_blocked, p_whole)


def test_the_cache_is_given_back_unless_planted(monkeypatch):
    if not torch.cuda.is_available():
        pytest.skip("no CUDA")
    x = torch.empty(64 * 1048576, dtype=torch.uint8, device="cuda"); del x
    assert torch.cuda.memory_reserved() >= 64 * 1048576 - 1
    monkeypatch.setenv("DOMVEC_PLANT_KEEP_TORCH_CACHE", "1")
    kept = torch.cuda.memory_reserved(); pm._give_back_cache()
    assert torch.cuda.memory_reserved() == kept
    monkeypatch.delenv("DOMVEC_PLANT_KEEP_TORCH_CACHE")
    pm._give_back_cache()
    assert torch.cuda.memory_reserved() < kept
