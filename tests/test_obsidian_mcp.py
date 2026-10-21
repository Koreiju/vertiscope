"""The MCP server's protocol behaviour.

Written against the protocol rather than the happy path, because the ways an
MCP server fails are mostly protocol ways: a notification that gets answered,
a tool error escalated to a transport error, a version echoed that the client
never offered. Each of those presents to the user as a hang or an unexplained
disconnect, with nothing in the output naming the cause.
"""

import io
import json

import pytest

from vertiscope.obsidian.mcp import VertiscopeMCP, serve_stdio


HOME = ("<html><body><h1>Home</h1><p>the front page</p>"
        "<a href='https://a.test/sub.html'>go on</a></body></html>")


@pytest.fixture()
def server(tmp_path):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        ws.index_html(HOME, "https://a.test")
        yield VertiscopeMCP(ws), ws


def _call(server, name, **arguments):
    reply = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def _payload(result):
    return json.loads(result["content"][0]["text"])


# --- protocol -----------------------------------------------------------------

def test_a_notification_is_never_answered(server):
    """Replying to a notification is a protocol error.

    Some clients surface it only as a hang, so this is asserted rather than
    left to manual observation.
    """
    mcp, _ = server
    assert mcp.handle({"jsonrpc": "2.0",
                       "method": "notifications/initialized"}) is None


def test_initialize_echoes_a_version_it_can_speak(server):
    """Version negotiation is a handshake, not a constant.

    Pinning one version would refuse clients the server can serve; echoing
    whatever the client sent would claim ones it cannot.
    """
    mcp, _ = server
    old = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05"}})
    assert old["result"]["protocolVersion"] == "2024-11-05"

    future = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "1999-01-01"}})
    assert future["result"]["protocolVersion"] != "1999-01-01"


def test_a_failing_tool_is_a_result_not_a_transport_error(server):
    """The model has to see the message and choose again.

    Escalating to a JSON-RPC error denies it that: the client raises and the
    tool result never reaches the conversation.
    """
    mcp, _ = server
    result = _call(mcp, "chunk", cid="does-not-exist")
    assert result["isError"] is True
    assert "does-not-exist" in result["content"][0]["text"]


def test_an_unknown_tool_is_a_protocol_error(server):
    """Distinct from the above: the call itself was malformed."""
    mcp, _ = server
    reply = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "nope", "arguments": {}}})
    assert reply["error"]["code"] == -32602


def test_every_advertised_tool_is_dispatchable(server):
    """A tool listed but not wired is invisible until a model tries it."""
    mcp, _ = server
    listed = {t["name"] for t in mcp.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]}
    assert listed == set(mcp.handlers)


# --- what the tools answer -----------------------------------------------------

def test_a_chunk_carries_addresses_not_just_text(server):
    """The address is the point: text alone is a picture of the page."""
    mcp, ws = server
    cid = ws.store.chunks("https://a.test")[0].cid
    payload = _payload(_call(mcp, "chunk", cid=cid))
    assert payload["lines"]
    assert all("key" in line for line in payload["lines"])


def test_an_address_resolves_back_to_its_chunk(server):
    """The navigational requirement, round-tripped."""
    mcp, ws = server
    cid = ws.store.chunks("https://a.test")[0].cid
    key = next(l["key"] for l in _payload(_call(mcp, "chunk", cid=cid))["lines"]
               if l["key"])
    back = _payload(_call(mcp, "resolve_address", address=key))
    assert back["chunk"] is not None
    assert back["chunk"]["cid"] == cid


def test_there_is_no_tool_that_writes(server):
    """Read-only is a property of the surface, not of how it is called."""
    mcp, _ = server
    assert not {name for name in mcp.handlers
                if any(verb in name
                       for verb in ("write", "edit", "delete", "press",
                                    "click", "enact", "navigate"))}


# --- transport ------------------------------------------------------------------

def test_stdio_writes_one_json_line_per_request(server):
    """stdout carries the protocol and nothing else.

    A stray print corrupts the stream and the client reports a parse error
    with no clue where it came from.
    """
    mcp, ws = server
    lines = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ])
    out = io.StringIO()
    serve_stdio(mcp.ws, stdin=io.StringIO(lines), stdout=out)

    replies = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert len(replies) == 2, "the notification drew a reply"
    assert [r["id"] for r in replies] == [1, 2]
