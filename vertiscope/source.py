"""A source file, addressed like a page.

`G-49` asks for the local codebase inside the patricia trie, beside the web
scans and the vault. `G-52` says what may be VECTORISED out of it: *"only
vectorizing comments and docstrings and not the actual code itself"*.

This module is the first half; the second half is one flag on
:func:`vertiscope.tokens.for_model`.

**The url.** ``code://<root>/<relative/path.py>``, exactly parallel to
`vertiscope.vault`'s ``vault://<vault>/<note.md>``. `address.url_steps` splits on
`urlsplit`, so the root is the origin and the path is segments -- which is the
shape a global trie wants, since files group by repository before they group
by folder. Nothing new is being invented here: `Workspace.index_html` already
addresses local files as ``file://`` and the vault already addresses notes as
``vault://``.

**The xpath.** Python's own tree, in the sensor's spelling: every step is
``name[ordinal]`` counted per parent and per kind, which is what
`core/js/sensor.js::stepFor` does for DOM children. So `ContentAddress.shape`
works unchanged and a module's addresses read alongside a page's rather than
in a second dialect::

    module docstring        ->  /module[1]/docstring[1]
    import block            ->  /module[1]/code[1]
    class Store:            ->  /module[1]/class[1]
      its docstring         ->  /module[1]/class[1]/docstring[1]
      def get(...)          ->  /module[1]/class[1]/function[1]
        its docstring       ->  /module[1]/class[1]/function[1]/docstring[1]
        its body            ->  /module[1]/class[1]/function[1]/code[1]
    # a standalone comment  ->  /module[1]/comment[3]

**Why a scope CONTAINS its members here, where a markdown heading does not.**
`vertiscope/vault.py` had to invent a ``section`` wrapper because a markdown
heading *names* the section it opens rather than containing it, and nesting
blocks under the heading asserted a containment markdown never meant. Python
is the opposite case and needs no wrapper: a class statement genuinely
contains its methods, the language says so with indentation, and `ast` hands
back that containment directly. Where the tree is real, use it.

**The taxonomy.** Existing categories only, the same discipline the vault
follows. A docstring and a comment are ``text`` / ``visible`` -- they are
prose a person reads, which is exactly what that subcategory means. Code is
``text`` / ``code``. No new category is invented, so nothing downstream has to
learn a word.

**What is NOT here.** These addresses are not evaluable XPath and nothing
should resolve one against a DOM; they are re-resolvable by re-parsing the
file, which is the same contract `vertiscope/vault.py` states and the same one
`sensing._xpath` already lives with for ``#shadow-root`` steps.

Only Python is parsed structurally. Another language gets its comments by a
line scan or nothing at all, and saying so is better than pretending a regex
is a parser -- see :func:`tag_source`.
"""

from __future__ import annotations

import ast
import io
import pathlib
import tokenize
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from .core.content_tagger import ContentTag

#: Files worth reading at all. A repository is mostly not source, and walking
#: a `node_modules` or a `build/` into the trie would drown the corpus it is
#: meant to join.
#: `.js` is here for `G-50`: the fold a reader watches run is
#: `core/js/sensor.js`, and a corpus that held every Python file and
#: not that one would be missing the thing the requirement names.
#: It gets COMMENTS, not structure -- see :func:`_js_comments`.
SOURCE_SUFFIXES = (".py", ".js")

#: Directories never descended. Not a style preference: `build/` here holds
#: multi-gigabyte kuzu stores, and `__pycache__` holds compiled copies of the
#: very files being indexed, so both would double-count the corpus.
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "build", "build_live", "build_sweep", "build_analytics", "dist",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "logs", ".obsidian",
})


def iter_sources(root):
    """Every source file under `root`, as ``(path, relative_posix_path)``.

    Skips `SKIP_DIRS` by NAME at any depth rather than by prefix: a nested
    `__pycache__` is as much a compiled copy as a top-level one, and a rule
    that only matched the top would index the same file twice under two
    addresses.
    """
    base = pathlib.Path(root).resolve()
    for path in sorted(base.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        yield path, rel.as_posix()


def source_url(root: str, rel_path: str) -> str:
    """``code://<root>/<rel_path>``, with the path POSIX-spelled.

    Windows hands back backslashes and a url has forward ones. The vault url
    makes the same correction for the same reason: an address that spells the
    same file two ways is two addresses.
    """
    clean = PurePosixPath(str(rel_path).replace("\\", "/")).as_posix()
    return "code://%s/%s" % (str(root).strip("/"), clean.lstrip("/"))


def source_path_of(url: str) -> Optional[Tuple[str, str]]:
    """``(root, rel_path)`` for a ``code://`` url, or None for anything else."""
    if not url.startswith("code://"):
        return None
    rest = url[len("code://"):]
    root, _, path = rest.partition("/")
    if not root or not path:
        return None
    return root, path


class _Addresser:
    """Ordinals per parent and per kind, the way the sensor counts children.

    Kept as a class rather than a dict-of-counters so the nesting reads like
    the tree it is numbering: `step` is always relative to a parent xpath, and
    the parent is passed rather than remembered, because an `ast` walk
    descends and returns and a remembered parent would survive the return.
    """

    def __init__(self) -> None:
        self._counts: Dict[Tuple[str, str], int] = {}

    def step(self, name: str, parent: str = "") -> str:
        key = (parent, name)
        self._counts[key] = self._counts.get(key, 0) + 1
        return "%s/%s[%d]" % (parent, name, self._counts[key])


def _docstring_of(node) -> Optional[str]:
    try:
        got = ast.get_docstring(node, clean=True)
    except Exception:                               # noqa: BLE001
        return None
    return got.strip() if got else None


def _kind_of(node) -> Optional[str]:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function"
    return None


def _import_targets(tree, root: str, rel_path: str):
    """Each `import` in the module, as (module_name, code:// url).

    **Resolved inside the same root only.** `import numpy` could mean
    the installed package, but which one depends on an interpreter and
    a path, and guessing wrong writes an edge to a file that is not
    the one imported. A relative or same-root module resolves to a
    path this root actually contains; anything else is still EMITTED,
    with the url it would have, and the store's existing rule takes
    over: a link becomes an edge only when its target is a page we
    hold. So indexing numpy later turns those edges on with no
    re-parse, which is exactly how a hyperlink to an unscanned page
    behaves.
    """
    here = PurePosixPath(rel_path)
    package = here.parent
    out = []

    def add(name: str, level: int = 0) -> None:
        if not name:
            return
        parts = name.split('.')
        if level:
            base = package
            for _ in range(level - 1):
                base = base.parent
            target = base.joinpath(*parts)
        else:
            target = PurePosixPath(*parts)
        # A package imports as its `__init__`, a module as itself.
        # Both spellings are offered so whichever the store holds
        # matches; the resolver drops the one it does not have.
        out.append((name, source_url(root, str(target) + '.py')))
        out.append((name, source_url(root, str(target / '__init__.py'))))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # BOTH spellings. `from pkg import lib` may import a submodule
            # `pkg.lib` or a name defined in `pkg`, and which one it is
            # cannot be known without importing it. Each candidate is
            # offered and the store's own rule decides: a link becomes an
            # edge only when its target is a page we hold. The same strategy
            # as `.py` against `/__init__.py` above, for the same reason.
            base = node.module or ''
            add(base, node.level or 0)
            for alias in node.names:
                if alias.name and alias.name != '*':
                    add((base + '.' + alias.name) if base else alias.name,
                        node.level or 0)
    return out


def _js_comments(text: str):
    """``(line, comment_text)`` for a JavaScript-ish file.

    **A scanner, and deliberately not a parser.** The module docstring says
    another language gets its comments by a line scan or nothing at all, and
    this is that scan: it walks the file character by character, tracking
    whether it is inside a string, a template literal or a comment, so that
    a `//` inside `"http://x"` is not mistaken for one. That much is exact.

    What it does NOT handle is the regex literal: `/ab//c/.test(s)` is
    ambiguous without a full expression parser, since `/` opens a division or
    a regex depending on what preceded it. A regex containing `//` can
    therefore swallow the rest of its line. Stated rather than hidden, and
    measured -- on `core/js/sensor.js` the scan finds **1,000** comments
    over 2,870 lines, and a `//` inside a string literal is correctly
    not one of them.

    The alternative was to pretend a regex is a parser, which this repository
    has a rule about.
    """
    out = []
    i, n = 0, len(text)
    line = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                    if quote != "`":
                        break           # an unterminated ordinary string
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            body = text[i + 2:j].strip()
            if body:
                out.append((line, body))
            i = j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            block = text[i + 2:max(i + 2, j - 2)]
            started = line
            # A JSDoc block is prose with leading stars; strip them so the
            # encoder is not charged for punctuation.
            body = "\n".join(
                ln.strip().lstrip("*").strip() for ln in block.splitlines())
            body = "\n".join(ln for ln in body.splitlines() if ln)
            if body:
                out.append((started, body))
            line += block.count("\n")
            i = j
            continue
        i += 1
    return out


def tag_source(text: str, *,
               root: str = "repo", rel_path: str = "",
               lines_at: Optional[Dict[str, Tuple[int, int]]] = None,
               ) -> List[ContentTag]:
    """One Python file into addressed detections, in document order.

    ``lines_at``, when given, is filled with ``xpath -> (first_line,
    last_line)``, 0-based and inclusive -- the same OUT-PARAMETER contract
    `vault.tag_note` uses, and for the same reason: only this pass is looking
    at the text, so only this pass knows both the address and the lines.

    **A file that does not parse still gets indexed.** A syntax error is an
    ordinary state for a file someone is editing, and refusing it would make
    the corpus a function of whether the working tree happens to compile. It
    falls back to comments alone, which is the part `G-52` cares about
    anyway.
    """
    out: List[ContentTag] = []
    addr = _Addresser()

    def mark(xpath: str, first: int, last: int) -> None:
        if lines_at is not None:
            lines_at[xpath] = (first, last)

    def emit(xpath: str, sub: str, value: str, first: int, last: int) -> None:
        if not value.strip():
            return
        mark(xpath, first, last)
        out.append(ContentTag(xpath=xpath, category="text",
                              subcategory=sub, value=value,
                              source_attr="source"))

    lines = text.splitlines()
    if str(rel_path).endswith(".js"):
        # Comments and the file itself. No structural parse: see
        # `_js_comments` for what that costs and why it is the honest
        # trade.
        module = addr.step("module")
        for row, body in _js_comments(text):
            emit(addr.step("comment", module), "visible", body, row, row)
        emit(addr.step("code", module), "code", text, 0, max(len(lines) - 1, 0))
        return out

    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    module = addr.step("module")

    if tree is not None:
        doc = _docstring_of(tree)
        if doc:
            emit(addr.step("docstring", module), "visible", doc, 0, 0)

        def walk(node, parent_xpath: str) -> None:
            for child in getattr(node, "body", []):
                kind = _kind_of(child)
                if kind is None:
                    continue
                here = addr.step(kind, parent_xpath)
                first = getattr(child, "lineno", 1) - 1
                last = getattr(child, "end_lineno", first + 1) - 1
                mark(here, first, last)

                # The NAME is its own detection, so a reader searching for a
                # function finds the function rather than the paragraph that
                # happens to mention it.
                emit(addr.step("name", here), "visible",
                     getattr(child, "name", ""), first, first)

                inner = _docstring_of(child)
                if inner:
                    emit(addr.step("docstring", here), "visible", inner,
                         first, last)

                # The body, minus its docstring: the docstring is already an
                # address of its own and carrying it twice would make one
                # sentence two detections with different classes.
                body = ast.get_source_segment(text, child) or ""
                if inner:
                    body = body.replace('"""%s"""' % inner, "", 1)
                    body = body.replace("'''%s'''" % inner, "", 1)
                emit(addr.step("code", here), "code", body, first, last)

                walk(child, here)

        walk(tree, module)

    if tree is not None and rel_path:
        # An import is a LINK, categorised so that `ContentAddress.is_url`
        # says so and the store's existing `_link_pages` resolver picks it
        # up (`G-8`, `G-51`). Nothing new resolves it, nothing new ranks it:
        # `edges()` routes it and PageRank counts it, the same as a
        # hyperlink, which is the whole point of spending an address on it.
        seen_imports = set()
        for name, target in _import_targets(tree, root, rel_path):
            if target in seen_imports:
                continue
            seen_imports.add(target)
            xpath = addr.step("import", module)
            mark(xpath, 0, 0)
            out.append(ContentTag(xpath=xpath, category="urls",
                                  subcategory="import", value=target,
                                  source_attr="import"))

    # Comments, from the tokeniser rather than a regex: a `#` inside a string
    # is not a comment, and only a tokeniser knows the difference.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            body = tok.string.lstrip("#").strip()
            if not body:
                continue
            row = tok.start[0] - 1
            emit(addr.step("comment", module), "visible", body, row, row)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file that will not tokenise still has its structure from `ast`,
        # or nothing -- either way, not a reason to lose the whole file.
        pass

    if not out and lines:
        # Nothing recognised. Index it as one code block rather than dropping
        # it, so the corpus's denominator is files-on-disk and not
        # files-we-happened-to-parse.
        emit(addr.step("code", module), "code", text, 0, len(lines) - 1)

    return out
