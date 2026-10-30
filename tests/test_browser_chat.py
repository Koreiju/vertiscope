"""The browser cell's chat (`G-43`..`G-45`, `domvec/chat.py`).

A turn carries the chunks pinned since the last reply, each at most once per
conversation -- enforced at the context window's edge, so a panel that
re-sends a chunk has it dropped and named. The model keeps the
conversation; a turn feeds only its new message. Planted `PLANT_RESEND`:
every turn carries every chunk pinned so far.
"""

from domvec import chat as C

A = {"cid": "a1", "url": "https://x/a", "markdown": "# Alpha\n\nThe alpha chunk."}
B = {"cid": "b2", "url": "https://x/b", "markdown": "# Beta\n\nThe beta chunk."}


def _conv():
    fed = []
    conv = C.Conversation("t", lambda text: (fed.append(text), "reply %d" % len(fed))[1])
    return conv, fed


def test_each_chunk_reaches_the_model_once():
    conv, fed = _conv()
    t1 = conv.ask("what is alpha?", [A])
    t2 = conv.ask("and beta?", [A, B])               # A again: the panel re-sent it
    t3 = conv.ask("compare them", [])
    assert "The alpha chunk." in fed[0] and "The alpha chunk." not in fed[1]
    assert "The beta chunk." in fed[1] and "The beta chunk." not in fed[2]
    assert t2.resent_dropped == ["a1"] and [c["cid"] for c in t2.context] == ["b2"]
    assert sorted(conv.sent) == ["a1", "b2"]
    assert t3.delta_chars < t1.delta_chars            # a bare prompt is a small delta
    assert fed[2].strip() == "compare them"


def test_the_prompt_follows_its_context_in_one_message():
    text = C.message("why?", [A])
    assert text.index("The alpha chunk.") < text.index("why?") and "https://x/a" in text


def test_reset_forgets_what_was_sent():
    conv, fed = _conv()
    conv.ask("q", [A])
    conv.reset()
    conv.ask("q again", [A])
    assert "The alpha chunk." in fed[1]


def test_planted_resend_puts_every_chunk_in_every_turn():
    conv, fed = _conv()
    C.PLANT_RESEND[0] = True
    try:
        conv.ask("one", [A])
        conv.ask("two", [B])
        conv.ask("three", [])
    finally:
        C.PLANT_RESEND[0] = False
    assert all("The alpha chunk." in f for f in fed)  # the defect: A in every turn
