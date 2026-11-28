"""Interactive, recursively chunked `tool` cells and slim smolagents dict schemas (`G-452`, `G-453`; PLUGIN_GOAL 201).

In trie terms:
- A tool cell at `vault://<vault>/<note>#tool <k>` projects a slice of the
  workspace's `tool://`, `https://`, or `vault://` patricia-trie chunks and
  interactive control addresses (`url|xpath`), along with inline markdown
  instructions for small language models.
- Each tool call is a slim single-key dictionary (`{"browser": {...}}`,
  `{"search": {...}}`, `{"cells": {...}}`, `{"terminal": {...}}`,
  `{"panel": {...}}`) sharing uniform navigation primitives (`search`, `back`,
  `forward`, `chunks`) so width and depth stay balanced inside quantized
  context windows.
- `chunks=True` steps into the linked child chunks / interactive controls of
  the current target; `back=True` / `forward=True` traverse the per-cell call
  stack without losing state; and each completed step yields a compact one-line
  markdown history summary to append directly above the ` ```tool ` fence.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

#: Planted (`G-453`): `/tool_cell` refuses execution and returns an inert stub.
PLANT_NO_TOOL_CELL = [False]

#: Default system prompt carried in `domvec/ego.md` (`## System prompt`) and
#: inherited by every ` ```chat ` cell unless overridden (`G-452`, PLUGIN_GOAL 201).
DEFAULT_EGO_SYSTEM_PROMPT = (
    "You operate inside an interactive Obsidian markdown + 3D/2D cell graph.\n"
    "Instantiate interactive cells with fenced blocks:\n"
    "- ```python ... ``` for executable code cells (variables share across linked notebooks in DAG order).\n"
    "- ```browser\\nhttps://...\\n``` for live web browser cells.\n"
    "- ```chat ... ``` for multi-turn local model cells.\n"
    "- ```tool\\n{\"browser\": {\"search\": \"...\", \"click\": \"\", \"next_chunk\": false, \"prev_chunk\": false, \"back\": false, \"forward\": false, \"chunks\": true}}\\n``` for slim interactive tool calls.\n"
    "Link cells in prose using standard markdown links `[cell title](path/to/cell.md)`.\n"
    "Set `\"chunks\": true` on any tool call to drill into its recursive child chunks and clickable controls; use `\"back\": true` / `\"forward\": true` to navigate the tool call stack."
)

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "browser": {
        "schema": {
            "search": "",
            "url": "",
            "click": "",
            "next_chunk": False,
            "prev_chunk": False,
            "back": False,
            "forward": False,
            "chunks": False,
        },
        "instructions": (
            "Browser toolspace: set `search` (page filter or web query), `url` (navigate), "
            "`click` (trie control `url|xpath` or control label), `next_chunk`/`prev_chunk` "
            "(step page chunks), `chunks=true` (expand interactive controls & child chunks), "
            "or `back`/`forward`."
        ),
    },
    "search": {
        "schema": {
            "search": "",
            "query": "",
            "where": "all",
            "k": 8,
            "back": False,
            "forward": False,
            "chunks": False,
        },
        "instructions": (
            "Retrieval toolspace: set `search` (or `query`) to rank store & vault chunks (`where`: `'all'`, `'web'`, `'ego'`). "
            "Set `chunks=true` to expand each hit's linked sub-chunks and controls."
        ),
    },
    "cells": {
        "schema": {
            "search": "",
            "open": "",
            "run": "",
            "back": False,
            "forward": False,
            "chunks": False,
        },
        "instructions": (
            "Cell-graph toolspace: `search` open/vault notebooks, `open` a cell on the 2D plane, "
            "`run` a notebook's code cells in DAG order, or set `chunks=true` to list cell headings & defs."
        ),
    },
    "terminal": {
        "schema": {
            "run": "",
            "search": "",
            "back": False,
            "forward": False,
            "chunks": False,
        },
        "instructions": (
            "Terminal toolspace: `run` a shell command or leave empty to read `Terminal.last()`; "
            "`search` filters output lines; `chunks=true` splits output into navigable chunks."
        ),
    },
    "panel": {
        "schema": {
            "cid": "",
            "search": "",
            "click": "",
            "value": "",
            "back": False,
            "forward": False,
            "chunks": False,
        },
        "instructions": (
            "Interactive panel toolspace: exposes every clickable/editable trie control on chunk `cid`. "
            "Set `click` to a control's trie address (`url|xpath`) and optional `value` to act in place."
        ),
    },
}

#: Per-cell navigation stacks in memory (`session_key -> {"entries": [...], "idx": int, "chunk_idx": int, "url": str}`).
_CELL_STACKS: Dict[str, Dict[str, Any]] = {}


def reset_stacks() -> None:
    _CELL_STACKS.clear()


def parse_tool_source(src: str) -> Dict[str, Any]:
    """Parse the body of a ` ```tool ` fence into `{mode, tool, args, instructions, app_tool}`."""
    raw = (src or "").strip()
    if not raw:
        return {
            "mode": "root",
            "tool": "root",
            "args": {},
            "instructions": "Select a toolspace below or write `{\"browser\": {\"search\": \"...\", \"chunks\": true}}` and exit the fence.",
        }

    # Check if the fence contains a JSON object (possibly preceded by `#` / `>` / prose instruction lines).
    lines = raw.splitlines()
    prose_lines: List[str] = []
    json_lines: List[str] = []
    in_json = False
    brace_depth = 0
    for ln in lines:
        s = ln.strip()
        if not in_json and s.startswith("{"):
            in_json = True
        if in_json:
            json_lines.append(ln)
            brace_depth += ln.count("{") - ln.count("}")
        else:
            prose_lines.append(ln)

    if json_lines:
        candidate = "\n".join(json_lines).strip()
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj:
                tool_name = next(iter(obj.keys()))
                val = obj[tool_name]
                if isinstance(val, dict):
                    t_key = tool_name.strip().lower()
                    schema_info = TOOL_SCHEMAS.get(t_key, {})
                    merged = dict(schema_info.get("schema") or {}, **val)
                    instr = "\n".join(l.lstrip("#> ").strip() for l in prose_lines if l.strip()).strip()
                    return {
                        "mode": "call",
                        "tool": t_key,
                        "args": merged,
                        "instructions": instr or schema_info.get("instructions") or "",
                    }
        except Exception:  # noqa: BLE001
            pass

    # Single bare word matching an app tool (`Database`, `WebBrowser`, `Vault`, etc.) -> G-421 read-only surface + interactive upgrade.
    first_token = raw.split()[0] if raw.split() else ""
    if len(lines) == 1 and re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", first_token):
        low = first_token.lower()
        if low in TOOL_SCHEMAS and first_token == low:
            # Lowercase `browser`, `search`, `cells`, `terminal`, `panel` opens interactive card!
            info = TOOL_SCHEMAS[low]
            return {
                "mode": "call",
                "tool": low,
                "args": dict(info["schema"]),
                "instructions": info["instructions"],
            }
        return {
            "mode": "app_tool",
            "tool": first_token,
            "args": {},
            "instructions": "",
        }

    return {
        "mode": "call",
        "tool": "search",
        "args": dict(TOOL_SCHEMAS["search"]["schema"], query=raw[:200]),
        "instructions": TOOL_SCHEMAS["search"]["instructions"],
    }


def format_tool_fence(tool: str, args: Dict[str, Any], instructions: str = "") -> str:
    """Render clean markdown-pure ` ```tool ` body with `#` instruction comment + compact JSON."""
    info = TOOL_SCHEMAS.get(tool, {})
    instr = (instructions or info.get("instructions") or "").strip()
    clean_args = {}
    base_schema = info.get("schema") or {}
    for k, v in args.items():
        if k in ("back", "forward", "next_chunk", "prev_chunk") and v is False and k in base_schema:
            clean_args[k] = False
        else:
            clean_args[k] = v
    payload = json.dumps({tool: clean_args}, ensure_ascii=False)
    if instr:
        first_line = instr.splitlines()[0].strip()
        return f"# {first_line}\n{payload}"
    return payload


def _page_chunks_from_store(workspace: Any, url: str) -> List[Dict[str, Any]]:
    if workspace is None or not url:
        return []
    base_url = url.split("#")[0]
    try:
        rows = workspace.store._rows(
            "MATCH (c:Chunk) WHERE c.url = $u OR c.url STARTS WITH $p "
            "RETURN c.cid, c.url, c.xpath, c.markdown LIMIT 120",
            {"u": base_url, "p": base_url + "#"},
        )
        out = []
        for cid, u, xp, md in rows:
            text = str(md or "").strip()
            first = next((l.strip() for l in text.splitlines() if l.strip()), str(xp or cid))
            out.append({
                "cid": str(cid),
                "url": str(u),
                "xpath": str(xp or ""),
                "title": first[:96],
                "markdown": text[:900],
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def _controls_of_chunk(workspace: Any, cid: str) -> List[Dict[str, Any]]:
    if workspace is None or not cid:
        return []
    try:
        pay = workspace.chunk_payload(cid) or {}
        controls = []
        url = str(pay.get("url") or "")
        for ln in pay.get("lines") or []:
            ctl = ln.get("control")
            key = str(ln.get("key") or "")
            if ctl and key:
                addr = f"{url}|{key}" if url and "|" not in key else key
                controls.append({
                    "address": addr,
                    "text": str(ln.get("text") or "").strip()[:80],
                    "control": ctl,
                    "call": {"panel": {"cid": cid, "click": addr, "chunks": False}},
                })
        return controls
    except Exception:  # noqa: BLE001
        return []


def execute(
    body: Dict[str, Any],
    workspace: Any = None,
    browser_state: Optional[Dict[str, str]] = None,
    shell_last: Optional[Dict[str, Any]] = None,
    vault_root: str = "",
) -> Dict[str, Any]:
    """Execute or navigate a ` ```tool ` cell and return its interactive render state."""
    if PLANT_NO_TOOL_CELL[0]:
        return {"ok": False, "planted": True, "error": "tool cells disabled (planted)"}

    session = str(body.get("session") or "default").strip() or "default"
    src = str(body.get("source") or "")
    parsed = body.get("call") if isinstance(body.get("call"), dict) else None
    if parsed:
        tool_name = next(iter(parsed.keys()), "browser").lower()
        args = dict(TOOL_SCHEMAS.get(tool_name, {}).get("schema") or {}, **(parsed.get(tool_name) or {}))
        instructions = str(body.get("instructions") or TOOL_SCHEMAS.get(tool_name, {}).get("instructions") or "")
        mode = "call"
    else:
        info = parse_tool_source(src)
        mode = info["mode"]
        tool_name = info["tool"]
        args = info["args"]
        instructions = info["instructions"]

    if mode == "root":
        cards = [
            {
                "tool": k,
                "title": f"tool:{k}",
                "instructions": v["instructions"],
                "call": {k: v["schema"]},
                "fence": format_tool_fence(k, v["schema"], v["instructions"]),
            }
            for k, v in TOOL_SCHEMAS.items()
        ]
        return {
            "ok": True,
            "mode": "root",
            "tool": "root",
            "instructions": instructions,
            "children": cards,
            "stack": {"index": 0, "total": 0, "can_back": False, "can_forward": False},
        }

    if mode == "app_tool":
        from . import tool_panels as _tp
        panels = _tp.render()
        text = panels.get(tool_name) or ""
        return {
            "ok": True,
            "mode": "app_tool",
            "tool": tool_name,
            "panel_text": text,
            "instructions": f"{tool_name} — app tool, read-only",
            "children": [
                {"tool": k, "title": f"switch to interactive `{k}`", "call": {k: v["schema"]}}
                for k, v in TOOL_SCHEMAS.items()
            ],
            "stack": {"index": 0, "total": 0, "can_back": False, "can_forward": False},
        }

    st = _CELL_STACKS.setdefault(session, {"entries": [], "idx": -1, "chunk_idx": 0, "url": ""})

    # Stack navigation (`back` / `forward`) without re-executing external side effects!
    if bool(args.get("back")) and st["idx"] > 0:
        st["idx"] -= 1
        prev = dict(st["entries"][st["idx"]])
        prev["stack"] = {
            "index": st["idx"] + 1,
            "total": len(st["entries"]),
            "can_back": st["idx"] > 0,
            "can_forward": st["idx"] < len(st["entries"]) - 1,
        }
        prev["navigated"] = "back"
        return prev

    if bool(args.get("forward")) and st["idx"] < len(st["entries"]) - 1:
        st["idx"] += 1
        nxt = dict(st["entries"][st["idx"]])
        nxt["stack"] = {
            "index": st["idx"] + 1,
            "total": len(st["entries"]),
            "can_back": st["idx"] > 0,
            "can_forward": st["idx"] < len(st["entries"]) - 1,
        }
        nxt["navigated"] = "forward"
        return nxt

    asks: List[Dict[str, Any]] = []
    children: List[Dict[str, Any]] = []
    markdown_out = ""
    summary_one_line = ""
    b_url = str((browser_state or {}).get("url") or st.get("url") or "")
    b_title = str((browser_state or {}).get("title") or "")

    if tool_name == "browser":
        target_url = str(args.get("url") or "").strip()
        q = str(args.get("search") or "").strip()
        click_target = str(args.get("click") or "").strip()
        want_chunks = bool(args.get("chunks"))
        if target_url:
            asks.append({"go": target_url})
            b_url = target_url
            st["url"] = target_url
            st["chunk_idx"] = 0
        chunks = _page_chunks_from_store(workspace, b_url)
        if q:
            filtered = [c for c in chunks if q.lower() in c["markdown"].lower() or q.lower() in c["title"].lower()]
            if filtered:
                chunks = filtered
            elif workspace is not None:
                # Fall back to workspace search or web search ask
                asks.append({"web": q})
        if bool(args.get("next_chunk")) and chunks:
            st["chunk_idx"] = min(len(chunks) - 1, int(st.get("chunk_idx") or 0) + 1)
        elif bool(args.get("prev_chunk")) and chunks:
            st["chunk_idx"] = max(0, int(st.get("chunk_idx") or 0) - 1)
        c_idx = max(0, min(int(st.get("chunk_idx") or 0), max(0, len(chunks) - 1)))
        cur_chunk = chunks[c_idx] if chunks else None

        if click_target:
            # Resolve by exact address or substring match on current chunk's controls.
            addr = click_target
            if "|" not in addr and cur_chunk:
                for ctl in _controls_of_chunk(workspace, cur_chunk["cid"]):
                    if click_target.lower() in ctl["text"].lower() or click_target in ctl["address"]:
                        addr = ctl["address"]
                        break
            asks.append({"act": {"address": addr, "value": None}})

        if cur_chunk:
            header = f"**{b_title or b_url}** · chunk `{c_idx + 1}/{len(chunks)}` (`{cur_chunk['cid'][:12]}`)"
            markdown_out = f"{header}\n\n{cur_chunk['markdown']}"
            if want_chunks:
                ctls = _controls_of_chunk(workspace, cur_chunk["cid"])
                for ctl in ctls[:16]:
                    children.append({
                        "kind": "control",
                        "title": f"[{ctl['control']}] {ctl['text'] or ctl['address']}",
                        "address": ctl["address"],
                        "call": ctl["call"],
                    })
                for idx_c, ch in enumerate(chunks[:16]):
                    children.append({
                        "kind": "chunk",
                        "cid": ch["cid"],
                        "title": f"chunk {idx_c + 1}: {ch['title']}",
                        "call": {"panel": {"cid": ch["cid"], "search": "", "click": "", "chunks": True}},
                    })
            summary_one_line = f"`browser` · {q or click_target or cur_chunk['title'][:48]} ({c_idx + 1}/{len(chunks)})"
        else:
            markdown_out = (
                f"**Browser** (`{b_url or 'no page open'}`)"
                + (f" — asked web search for `{q}`" if q else " — navigate or scan a page to browse its chunks.")
            )
            summary_one_line = f"`browser` · {q or target_url or b_url or 'idle'}"

    elif tool_name == "search":
        q = str(args.get("query") or args.get("search") or "").strip()
        where = str(args.get("where") or "all").strip()
        k = max(1, min(30, int(args.get("k") or 8)))
        want_chunks = bool(args.get("chunks"))
        hits: List[Dict[str, Any]] = []
        if q and workspace is not None:
            try:
                raw_hits = workspace.search(q, k=k)
                for h in raw_hits or []:
                    getf = (lambda key, default="": h.get(key, default)) if isinstance(h, dict) else (lambda key, default="": getattr(h, key, default))
                    u = str(getf("url", "") or "")
                    if where == "ego" and not u.startswith("vault://"):
                        continue
                    if where == "web" and u.startswith("vault://"):
                        continue
                    cid = str(getf("cid", "") or "")
                    prev = str(getf("preview", "") or getf("markdown", "") or getf("text", "") or "").strip()
                    first = next((l.strip() for l in prev.splitlines() if l.strip()), u)
                    hits.append({"cid": cid, "url": u, "title": first[:96], "preview": prev[:280], "score": float(getf("score", 0.0) or 0.0)})
            except Exception:  # noqa: BLE001
                pass
        if hits:
            lines = [f"**Search** `{q}` ({len(hits)} hits):"]
            for i, h in enumerate(hits):
                lines.append(f"{i + 1}. **{h['title']}** (`{h['url']}` · `{h['score']:.3f}`)")
                if want_chunks:
                    children.append({
                        "kind": "chunk",
                        "cid": h["cid"],
                        "url": h["url"],
                        "title": f"{i + 1}. {h['title']}",
                        "call": {"panel": {"cid": h["cid"], "search": "", "click": "", "chunks": True}},
                    })
            markdown_out = "\n".join(lines)
        else:
            markdown_out = f"**Search** `{q or '(empty)'}` — 0 hits."
        summary_one_line = f"`search` · \"{q}\" -> {len(hits)} hits"

    elif tool_name == "panel":
        cid = str(args.get("cid") or "").strip()
        click_addr = str(args.get("click") or "").strip()
        val = args.get("value")
        q = str(args.get("search") or "").strip()
        want_chunks = bool(args.get("chunks", True))
        if click_addr:
            asks.append({"act": {"address": click_addr, "value": None if val in ("", None) else str(val)}})
        pay = workspace.chunk_payload(cid) if (workspace is not None and cid) else None
        if pay:
            lines_raw = pay.get("lines") or []
            if q:
                lines_raw = [l for l in lines_raw if q.lower() in str(l.get("text") or "").lower()]
            rendered = "\n".join(str(l.get("text") or "") for l in lines_raw[:35]).strip()
            markdown_out = f"**Panel `{cid[:12]}`** (`{pay.get('url') or ''}`)\n\n{rendered}"
            if want_chunks:
                for ctl in _controls_of_chunk(workspace, cid)[:20]:
                    children.append({
                        "kind": "control",
                        "title": f"[{ctl['control']}] {ctl['text'] or ctl['address']}",
                        "address": ctl["address"],
                        "call": ctl["call"],
                    })
            summary_one_line = f"`panel` · `{cid[:10]}`" + (f" click `{click_addr.split('|')[-1]}`" if click_addr else "")
        else:
            markdown_out = f"**Panel** `{cid or '(no cid)'}` — select a chunk to inspect its interactive controls."
            summary_one_line = f"`panel` · {cid or 'empty'}"

    elif tool_name == "cells":
        import pathlib
        q = str(args.get("search") or "").strip().lower()
        open_target = str(args.get("open") or "").strip()
        run_target = str(args.get("run") or "").strip()
        want_chunks = bool(args.get("chunks"))
        if open_target:
            asks.append({"open_note": open_target})
        if run_target:
            asks.append({"invoke": run_target})
        found_notes: List[Tuple[str, str]] = []
        if vault_root:
            gp = pathlib.Path(vault_root) / "domvec" / "graph"
            if gp.is_dir():
                for mf in sorted(gp.glob("*.md"))[:40]:
                    rel = f"domvec/graph/{mf.name}"
                    txt = mf.read_text(encoding="utf-8", errors="ignore")
                    title = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.strip().startswith("#")), mf.stem)
                    if not q or q in title.lower() or q in rel.lower() or q in txt.lower():
                        found_notes.append((title, rel))
                        if want_chunks:
                            children.append({
                                "kind": "cell",
                                "title": f"[{title}]({rel})",
                                "path": rel,
                                "call": {"cells": {"search": "", "open": rel, "run": "", "chunks": False}},
                            })
        bullets = "\n".join(f"- [{t}]({p})" for t, p in found_notes[:20]) or "*(no matching cells)*"
        markdown_out = f"**Cells** ({len(found_notes)} in graph):\n{bullets}"
        summary_one_line = f"`cells` · {open_target or run_target or q or f'{len(found_notes)} listed'}"

    elif tool_name == "terminal":
        cmd = str(args.get("run") or "").strip()
        q = str(args.get("search") or "").strip().lower()
        if cmd:
            asks.append({"terminal_run": cmd})
        last = shell_last or {}
        out_txt = str(last.get("output") or "")
        if q:
            out_txt = "\n".join(l for l in out_txt.splitlines() if q in l.lower())
        markdown_out = (
            f"**Terminal** (`{cmd or last.get('command') or 'idle'}`)\n\n"
            + (f"```text\n{out_txt[:800]}\n```" if out_txt.strip() else "*(no output yet)*")
        )
        if bool(args.get("chunks")) and out_txt.strip():
            lines_all = out_txt.splitlines()
            for b in range(0, min(len(lines_all), 60), 15):
                seg = "\n".join(lines_all[b:b + 15])
                children.append({
                    "kind": "chunk",
                    "title": f"lines {b + 1}..{min(len(lines_all), b + 15)}",
                    "preview": seg[:200],
                    "call": {"terminal": {"run": "", "search": lines_all[b][:24].strip(), "chunks": False}},
                })
        summary_one_line = f"`terminal` · `{cmd or last.get('command') or 'last'}`"

    else:
        markdown_out = f"Unknown tool `{tool_name}`. Available: {', '.join(sorted(TOOL_SCHEMAS))}."
        summary_one_line = f"`{tool_name}` · unknown"

    # Reset one-shot step flags (`back`, `forward`, `next_chunk`, `prev_chunk`, `click`) in canonical source
    saved_args = dict(args)
    for transient in ("back", "forward", "next_chunk", "prev_chunk"):
        if transient in saved_args:
            saved_args[transient] = False

    stamp = time.strftime("%H:%M:%S")
    history_line = f"> `{stamp}` {summary_one_line}"

    entry = {
        "ok": True,
        "mode": "call",
        "tool": tool_name,
        "args": saved_args,
        "instructions": instructions,
        "fence": format_tool_fence(tool_name, saved_args, instructions),
        "markdown": markdown_out,
        "children": children,
        "asks": asks,
        "history_line": history_line,
    }

    # Push onto stack (truncating any forward branch when making a fresh call)
    if st["idx"] < len(st["entries"]) - 1:
        st["entries"] = st["entries"][:st["idx"] + 1]
    if not st["entries"] or st["entries"][-1].get("fence") != entry["fence"] or st["entries"][-1].get("markdown") != entry["markdown"]:
        st["entries"].append(dict(entry))
        if len(st["entries"]) > 32:
            st["entries"] = st["entries"][-32:]
    st["idx"] = len(st["entries"]) - 1
    entry["stack"] = {
        "index": st["idx"] + 1,
        "total": len(st["entries"]),
        "can_back": st["idx"] > 0,
        "can_forward": False,
    }
    return entry
