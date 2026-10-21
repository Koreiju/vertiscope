"""The frequency index survives a crash mid-save (2026-10-07: a native crash
during `save` left `freq.npz` at 0 bytes and the store would not open again)."""

import numpy as np
import pytest

from vertiscope.vectors import FreqMatrix


def test_a_save_that_dies_midway_leaves_the_last_good_index(tmp_path, monkeypatch):
    m = FreqMatrix()
    m.add("c1", "alpha beta gamma")
    m.save(tmp_path)
    good = (tmp_path / "freq.npz").read_bytes()
    m.add("c2", "delta epsilon")

    def dies(*a, **k):
        raise OSError("crash mid-write")
    monkeypatch.setattr(np, "savez_compressed", dies)
    with pytest.raises(OSError):
        m.save(tmp_path)
    monkeypatch.undo()
    assert (tmp_path / "freq.npz").read_bytes() == good
    back = FreqMatrix.load(tmp_path)
    assert back.row_of("c1") is not None


def test_planted_writing_in_place_truncates(tmp_path):
    """The old way, planted: a file opened for writing in place is empty the
    moment the write starts -- what the crash left behind."""
    m = FreqMatrix()
    m.add("c1", "alpha beta gamma")
    m.save(tmp_path)
    with open(tmp_path / "freq.npz", "wb"):
        pass                                  # the crash, right after open
    with pytest.raises(Exception):
        FreqMatrix.load(tmp_path)
