"""G-384 live: a quantized agent on CUDA uses the kernel's tool panels against the
running sidecar and writes its run as cells (`DOMVEC_LIVE=1`, `DOMVEC_SIDECAR`).

Read-only on the store. Planted arm: the `search` tool answers nothing -- the
agent can no longer name a stored url, and the check must see that.
"""

import json
import os
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("DOMVEC_LIVE") != "1", reason="live: the sidecar and a 7B GGUF on CUDA")
BASE = os.environ.get("DOMVEC_SIDECAR", "http://127.0.0.1:8794")
TASK = ("Use the search tool to find chunks about 'web browser'. "
        "Return only the url of the first result, as a string, with final_answer.")


def _pages():
    with urllib.request.urlopen(BASE + "/pages", timeout=60) as r:
        return set(json.load(r)["urls"])


@pytest.fixture(scope="module")
def model():
    from domvec.agent_model import LlamaCppModel
    return LlamaCppModel.for_task("code", max_tokens=256, temperature=0.0)


def _agent(model, tools):
    from smolagents import CodeAgent
    from smolagents.monitoring import LogLevel
    return CodeAgent(tools=tools, model=model, code_block_tags="markdown", max_steps=4,
                     verbosity_level=LogLevel.OFF)


def test_the_agent_finds_a_stored_url_with_the_kernels_search(model, tmp_path):
    from domvec import agent_step, agent_tools, dataflow
    a = _agent(model, agent_tools.tools(BASE))
    note = agent_step.run_note(a, TASK)
    (tmp_path / "run.md").write_text(note, encoding="utf-8")
    answer = str(a.memory.steps[-1].action_output or "")
    assert answer in _pages(), (answer, note)
    assert note.count("```python") >= 1 and "<!-- nb-output " in note
    g = dataflow.graph(note, known={"search", "cypher", "page_chunks", "final_answer"})
    assert not [p for p in g.problems if p.kind == "SyntaxError"]
    print(json.dumps({"answer": answer, "steps": note.count("```python")}))


def test_planted_empty_search_cannot_name_a_stored_url(model):
    from smolagents import Tool
    from domvec import agent_tools

    class Empty(Tool):
        name = "search"
        description = agent_tools._Search.description
        inputs = agent_tools._Search.inputs
        output_type = "array"

        def forward(self, query: str, k: int = 5):
            return []
    a = _agent(model, [Empty()])
    try:
        a.run(TASK)
    except Exception:                                  # noqa: BLE001 -- giving up is a fine outcome here
        pass
    answer = str(getattr(a.memory.steps[-1], "action_output", "") or "")
    assert answer not in _pages()
