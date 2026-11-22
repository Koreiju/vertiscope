"""ONE model table (THROUGH_STACK_SYNTHESIS 1b, PLUGIN_GOAL 181)."""

import pytest

from domvec import models
from domvec.obsidian import kernel_objects as ko


def test_every_reader_of_a_model_file_reads_the_one_table():
    agent_model = pytest.importorskip("domvec.agent_model")
    from domvec import chat
    assert chat.MODEL_FILE == models.ROLES["chat"]["file"]
    for task, f in agent_model.TASK_MODELS.items():
        assert models.ROLES[task]["file"] == f
    # The disagreement it replaced: chat was DeepSeek-Coder here and Hermes there.
    assert models.ROLES["chat"]["file"].startswith("Nous-Hermes")
    assert models.ROLES["coder"]["file"].startswith("deepseek-coder")


def test_a_role_that_is_not_prompt_to_code_is_refused_without_loading_anything():
    res = models.run_chat("hello", role="triplex")
    assert not res.ok and "not a prompt" in res.error and res.role == "triplex"


def test_find_looks_in_both_places(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (b / "m.gguf").write_bytes(b"x")
    monkeypatch.setattr(models, "MODEL_DIRS", [a, b])
    assert models.find("m.gguf") == b / "m.gguf"
    assert models.find("absent.gguf") is None


def test_the_kernel_bootstrap_carries_run_role():
    ns = {}
    exec(compile(ko.boot("http://127.0.0.1:9"), "<boot>", "exec"), ns)
    assert callable(ns["run_role"])
