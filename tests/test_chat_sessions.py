"""Unit tests for persistent multi-turn quantized chat sessions & O(delta) pins (`G-444`)."""

from __future__ import annotations

from domvec import chat


def test_stream_session_persists_turns_and_deduplicates_pins():
    sess = chat.StreamSession("test/nb9.md")
    pin_a = {"cid": "cidA", "url": "https://example.org/a", "title": "Page A", "markdown": "Alpha codeword is ORION-9."}
    pin_b = {"cid": "cidB", "url": "https://example.org/b", "title": "Page B", "markdown": "Beta port is 9443."}

    # Turn 1: pin A + note block 1 -> 0 prior turns, pin A sent once.
    msgs1, meta1 = sess.prepare("Remember the codeword.", context=["x = 42"], pins=[pin_a], history=[])
    assert [m["role"] for m in msgs1] == ["system", "user"]
    assert meta1["history_turns"] == 0
    assert meta1["fresh_pins"] == ["cidA"]
    assert meta1["dropped_pins"] == []
    assert meta1["fresh_blocks"] == 1
    assert "ORION-9" in msgs1[-1]["content"]
    sess.commit(meta1, "Understood, codeword ORION-9 noted.")

    # Turn 2: pin A still pinned + new pin B, unchanged note block `x = 42`.
    # Pin A and unchanged `x = 42` MUST be dropped from the delta, while Turn 1
    # stays in `msgs2` as USER/ASSISTANT history and pin B enters as delta!
    msgs2, meta2 = sess.prepare(
        "What are both the codeword and port?",
        context=["x = 42"],
        pins=[pin_a, pin_b],
        history=[{"user": "Remember the codeword.", "assistant": "Understood, codeword ORION-9 noted."}],
    )
    assert [m["role"] for m in msgs2] == ["system", "user", "assistant", "user"]
    assert meta2["history_turns"] == 1
    assert meta2["fresh_pins"] == ["cidB"]
    assert meta2["dropped_pins"] == ["cidA"]
    assert meta2["fresh_blocks"] == 0
    assert meta2["dropped_blocks"] == 1
    assert "ORION-9" not in msgs2[-1]["content"]
    assert "ORION-9" in msgs2[1]["content"]
    assert "9443" in msgs2[-1]["content"]
    sess.commit(meta2, "ORION-9 and 9443.")

    # Turn 3: edited cell block (`x = 99`) IS injected as fresh delta.
    msgs3, meta3 = sess.prepare("What changed?", context=["x = 99"], pins=[pin_a, pin_b])
    assert meta3["history_turns"] == 2
    assert meta3["fresh_pins"] == []
    assert sorted(meta3["dropped_pins"]) == ["cidA", "cidB"]
    assert meta3["fresh_blocks"] == 1
    assert "x = 99" in msgs3[-1]["content"]


def test_stream_session_rehydrates_from_note_markdown_when_cold_and_clears_on_wipe():
    sess = chat.StreamSession("test/cold_rehydrate.md")
    seed = [
        {"user": "First question", "assistant": "First answer"},
        {"user": "Second question", "assistant": "Second answer"},
    ]
    msgs, meta = sess.prepare("Third question", context=[], pins=[], history=seed)
    assert meta["history_turns"] == 2
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
    sess.commit(meta, "Third answer")
    assert sess.to_json()["turns"] == 3

    # Clearing all turns in the note resets the mirrored session (spec F-82).
    msgs_after_clear, meta_clear = sess.prepare("Fresh start", context=[], pins=[], history=[])
    assert meta_clear["history_turns"] == 0
    assert [m["role"] for m in msgs_after_clear] == ["system", "user"]


def test_planted_chat_oneshot_drops_history_and_resends_pins():
    """Non-vacuity check: `PLANT_CHAT_ONESHOT` reproduces the old stateless bug."""
    sess = chat.StreamSession("test/planted_oneshot.md")
    pin_a = {"cid": "cidA", "url": "https://example.org/a", "markdown": "Fact A"}
    msgs1, meta1 = sess.prepare("Turn 1", context=["cell = 1"], pins=[pin_a])
    sess.commit(meta1, "Reply 1")
    assert sess.to_json()["turns"] == 1

    chat.PLANT_CHAT_ONESHOT[0] = True
    try:
        msgs2, meta2 = sess.prepare("Turn 2", context=["cell = 1"], pins=[pin_a])
        assert meta2["oneshot"] is True
        assert meta2["history_turns"] == 0
        assert [m["role"] for m in msgs2] == ["system", "user"]
        assert meta2["dropped_pins"] == []
        assert meta2["fresh_pins"] == ["cidA"]
    finally:
        chat.PLANT_CHAT_ONESHOT[0] = False
