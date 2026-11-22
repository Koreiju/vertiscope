"""The chat model gives its VRAM back when idle (chat_cuda.IDLE_S; PLUGIN_GOAL 171 c's converse).

No GPU needed: a stand-in model records whether it was closed. Planted
PLANT_NEVER_RELEASE keeps it resident, as before.
"""

from domvec import chat_cuda as cc


class _Llm:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Model:
    def __init__(self):
        self._llm = _Llm()


def _resident(monkeypatch, last=0.0, in_use=0):
    m = _Model()
    monkeypatch.setattr(cc, "_MODEL", [m])
    monkeypatch.setattr(cc, "_LAST_USE", [last])
    monkeypatch.setattr(cc, "_IN_USE", [in_use])
    monkeypatch.setattr(cc, "STATS", dict(cc.STATS, released=0))
    return m


def test_idle_model_is_closed_and_dropped(monkeypatch):
    m = _resident(monkeypatch, last=1000.0)
    llm = m._llm
    assert cc.release_if_idle(now=1000.0 + cc.IDLE_S + 1)
    assert llm.closed and cc._MODEL[0] is None and cc.STATS["released"] == 1
    assert cc.loaded_on() == ""


def test_not_released_while_recent_or_in_use(monkeypatch):
    _resident(monkeypatch, last=1000.0)
    assert not cc.release_if_idle(now=1000.0 + cc.IDLE_S - 1)
    _resident(monkeypatch, last=0.0, in_use=1)
    assert not cc.release_if_idle(now=10 ** 9)
    assert cc._MODEL[0] is not None


def test_planted_never_release(monkeypatch):
    m = _resident(monkeypatch, last=0.0)
    monkeypatch.setattr(cc, "PLANT_NEVER_RELEASE", [True])
    assert not cc.release_if_idle(now=10 ** 9)
    assert cc._MODEL[0] is m and not m._llm.closed
