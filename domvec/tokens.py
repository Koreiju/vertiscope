"""How long a rendered chunk is, in the unit the context window is stated in.

The chunker has always compared a subtree's render against ``context_window``
and never said what the numbers were. They were characters -- ``len`` of the
markdown -- and the default window was 1200 of them, which is about 400
tokens. Every consumer downstream of the chunker measures in tokens: an
embedder's input limit, a model's context, the budget a retrieval result has
to fit into. So the knob that decides how much goes in a chunk was denominated
in a unit no consumer uses, and "the window" was roughly a twentieth of any
real one. Measured on the fixture corpus: 98 chunks, median 165 tokens, filling
8% of a 2048-token window.

This module makes the unit explicit and switchable, and the switch is what
matters. A window is a number *and* a unit, and a number carried without its
unit will be read in whichever one the reader assumes.

The count is over the **markdown rendering** -- the string a chunk actually
becomes -- and not over the page's text, the trie's values, or the HTML. Those
differ: the render adds link syntax, indentation and control marks, and the
markdown is what is embedded, what is stored, and what a reader is served. A
budget enforced on one string and spent on another is not a budget.

Not the same question as `MarkdownChunk.chars`, which stays what it says.
"""

from __future__ import annotations

from typing import Callable, Dict, Tuple

#: The encoding to count with when nothing else is asked for. cl100k_base is
#: the BPE behind the GPT-4 family and is within a few percent of the
#: SentencePiece vocabularies used by the local embedders on ordinary prose --
#: close enough that a window set in one is not badly wrong in the other, and
#: the alternative is loading a model to measure a string.
DEFAULT_ENCODING = "cl100k_base"

#: Characters per token when there is no tokeniser to ask. Measured over this
#: repo's own rendered corpus, which runs denser than prose because link
#: targets tokenise badly: 68,298 characters to 22,575 tokens is 3.03. Rounded
#: DOWN to 3.0 so the estimate over-counts tokens slightly and the window is
#: undershot rather than blown.
CHARS_PER_TOKEN = 3.0

_UNITS = ("chars", "tokens")

#: Tokens by default, because `DEFAULT_CONTEXT_WINDOW` is a token count. A
#: module whose default unit disagreed with the default window would be a
#: window three times smaller than it reads, which is the exact confusion this
#: module exists to end.
_name = "tokens"
#: Resolved on first use, never at import. `tiktoken.get_encoding` reads a BPE
#: file it may have to *download*, and a library that reaches the network
#: when it is imported is a library that fails on an offline machine at the
#: one moment nothing has asked it for anything yet.
_encoder = None
_resolved = False
_cache: Dict[Tuple[int, int], int] = {}
#: Bounded so a long crawl cannot grow it without limit. Cleared wholesale
#: rather than evicted one at a time: the entries are worth microseconds each
#: and an LRU over them would cost more to maintain than to lose.
_CACHE_CAP = 100_000


def use(unit: str = "tokens", *, encoding: str = DEFAULT_ENCODING) -> str:
    """Choose the unit windows are measured in. Returns the unit in force.

    Returns rather than asserts, because the tokeniser may not be installed
    and the caller has to be able to find out. Asking for ``tokens`` on a
    machine without ``tiktoken`` gets ``tokens-estimated`` back -- a
    characters-over-3 approximation, named differently so that no report can
    claim a measured token count it did not measure.
    """
    global _name, _encoder, _resolved
    if unit not in _UNITS:
        raise ValueError("unit must be one of %s" % (_UNITS,))
    _cache.clear()
    if unit == "chars":
        _name, _encoder, _resolved = "chars", None, True
        return _name
    _name, _encoder, _resolved = "tokens", None, False
    return _resolve()


def _resolve() -> str:
    """Load the tokeniser if it has not been loaded, and settle the name."""
    global _name, _encoder, _resolved
    if _resolved:
        return _name
    _resolved = True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding(DEFAULT_ENCODING)
        _name = "tokens"
    except Exception:                                   # noqa: BLE001
        _encoder = None
        _name = "tokens-estimated"
    return _name


def name() -> str:
    """The unit in force, for reports that state what they measured.

    Resolves the tokeniser rather than reporting the intent, because this
    name goes into the render memo's key. A name that changed from `tokens`
    to `tokens-estimated` on the first count would put two different units'
    numbers under one key inside a single render.
    """
    return _resolve()


def count(text: str) -> int:
    """``text``'s length in the unit in force.

    Cached on the string, because the descent renders speculatively: a subtree
    is measured once by itself and again by each of its ancestors deciding
    whether to keep it whole. The render memo absorbs most of that, but the
    no-memo path re-renders, and a tokeniser call is a hundred times the cost
    of a ``len``.
    """
    if not _resolved:
        _resolve()
    if _encoder is None:
        if _name == "chars":
            return len(text)
        return int(len(text) / CHARS_PER_TOKEN) + 1 if text else 0

    key = (len(text), hash(text))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    # `disallowed_special=()` so that a page containing the literal text
    # `<|endoftext|>` is counted rather than raising. The chunker measures
    # whatever the web gave it, and a scraper that crashes on a string a page
    # is allowed to contain is a scraper with a hole in it.
    n = len(_encoder.encode(text, disallowed_special=()))
    if len(_cache) >= _CACHE_CAP:
        _cache.clear()
    _cache[key] = n
    return n


def measure() -> Callable[[str], int]:
    """The counting function itself, for a caller that wants to hold it."""
    return count


def sensor_budget(window: int) -> int:
    """``window`` restated in characters, for the in-browser pre-chunker.

    `sensor.js` splits the page before anything is rendered, and it counts
    characters: it runs in a page, and a BPE tokeniser is not something to
    ship into one. The two cutters are meant to work at the same granularity,
    so the window is converted rather than handed over -- passing a token
    count straight into a character budget makes the browser-side split about
    three times finer than the renderer's, and the renderer then has nothing
    left to merge.

    Under the ``chars`` unit this is the identity, because then there is
    nothing to convert.
    """
    if name() == "chars":
        return int(window)
    return int(window * CHARS_PER_TOKEN)
