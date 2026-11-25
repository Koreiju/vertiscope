"""G-412: Chat.messages mirrors the chat note's turns (the note is the record)."""
import os

from domvec.obsidian import kernel_objects as ko

NOTE = """# talk

some context above

> **You** what is a trie
> (asked twice)

A prefix tree.

It stores keys by position.

> **You** and a radix tree?

A compressed trie.

```chat
```
"""


def _ns(tmp_path, note="talk.md"):
    (tmp_path / note).write_text(NOTE, encoding="utf-8")
    cwd = os.getcwd()
    ns = {"_domvec_note": note}
    try:
        exec(ko.vault_boot(str(tmp_path), note), ns, ns)
    finally:
        os.chdir(cwd)
    return ns


def test_turns_in_order(tmp_path):
    m = _ns(tmp_path)["Chat"].messages()
    assert [x["role"] for x in m] == ["user", "assistant", "user", "assistant"]
    assert m[0]["content"] == "what is a trie\n(asked twice)"
    assert m[1]["content"] == "A prefix tree.\n\nIt stores keys by position."
    assert m[3]["content"] == "A compressed trie."


def test_a_note_without_turns_has_none(tmp_path):
    (tmp_path / "plain.md").write_text("# plain\n\ntext\n", encoding="utf-8")
    assert _ns(tmp_path)["Chat"].messages("plain.md") == []
