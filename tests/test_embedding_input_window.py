"""What the embedder actually SEES of a chunk.

A vector taken of the first third of a chunk is not a vector of the chunk, and
nothing anywhere raises when that happens: the shape is right, the values are
finite, cosine similarity still works, and the layout still looks like a
layout. It is only wrong.

This became reachable when the chunker's window moved to 2048 tokens -- about
6,000 characters -- against a crash guard set at 2000 characters and described
in its own comment as "~500 tokens". The guard, not the model, was deciding
what got embedded.

These tests do not need a model. What is being asserted is the relationship
between two numbers that live in different modules and must agree.
"""

import pytest

from vertiscope import tokens
from vertiscope.core.embedding_service import (NOMIC_MAX_TOKENS, _MAX_INPUT_CHARS,
                                           _truncate)
from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW


def test_the_guard_admits_a_whole_chunk_of_prose():
    """The guard is the effective limit, so it has to fit a whole chunk.

    `Embed4All` does not truncate at nomic's nominal context: measured, its
    time scales linearly with input right through 32k characters, so it reads
    everything it is given. That makes this cap the thing that decides what a
    vector is of -- and a cap sized from the AVERAGE characters-per-token cuts
    everything denser than average. This repo's own notes run 3.03 chars per
    token because link targets tokenise badly; ordinary prose runs about 4.3.
    """
    assert _MAX_INPUT_CHARS >= NOMIC_MAX_TOKENS * 5, (
        "the crash guard (%d chars) is tighter than %d tokens of ordinary "
        "prose, so it decides what gets embedded"
        % (_MAX_INPUT_CHARS, NOMIC_MAX_TOKENS))


def test_a_chunk_at_the_window_is_not_cut_before_it_is_embedded():
    """The chunker's window and the embedder's input have to agree.

    Two numbers in two modules with nothing tying them together. When they
    disagree the chunker fills a window the embedder never reads, and every
    semantic vector describes a prefix.
    """
    assert DEFAULT_CONTEXT_WINDOW <= NOMIC_MAX_TOKENS, (
        "chunks are cut to %d tokens but the embedder reads %d"
        % (DEFAULT_CONTEXT_WINDOW, NOMIC_MAX_TOKENS))

    # And in the unit the guard is written in. A window-sized chunk of real
    # rendered markdown must survive `_truncate` intact.
    line = ("A paragraph of ordinary prose about libraries and their "
            "catalogues, with [a link](https://books.test/a) in it. ")
    md = ""
    while tokens.count(md) < DEFAULT_CONTEXT_WINDOW:
        md += line
    assert _truncate(md) == md, (
        "a %d-token chunk (%d chars) was cut to %d chars before embedding"
        % (tokens.count(md), len(md), len(_truncate(md))))


def test_the_guard_still_guards():
    """Raising it must not have removed it.

    The failure it exists for is an access violation in the native library on
    unexpectedly long input, which takes the process down rather than raising.
    """
    huge = "x" * (_MAX_INPUT_CHARS * 4)
    assert len(_truncate(huge)) == _MAX_INPUT_CHARS


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_nothing_becomes_a_space_rather_than_a_crash(empty):
    assert _truncate(empty) == " " or _truncate(empty).strip() == ""
