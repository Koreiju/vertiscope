"""G-381: a GGUF file described from its header (domvec/gguf_meta.py).

The files are written here, byte by byte, to the GGUF specification -- no
model is downloaded. Planted arms: wrong magic, a truncated header, version 1.
"""

import struct

import pytest

from domvec import gguf_meta as gm


def _s(x: str) -> bytes:
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def _kv(k: str, t: int, v) -> bytes:
    out = _s(k) + struct.pack("<I", t)
    if t == 8:
        return out + _s(v)
    if t == 9:
        et, items = v
        out += struct.pack("<IQ", et, len(items))
        return out + b"".join(_s(i) if et == 8 else struct.pack(gm._SCALAR[et], i) for i in items)
    return out + struct.pack(gm._SCALAR[t], v)


def write(path, kvs, version=3, tensors=291, magic=b"GGUF"):
    body = magic + struct.pack("<IQQ", version, tensors, len(kvs)) + b"".join(_kv(*kv) for kv in kvs)
    path.write_bytes(body + b"\0" * 32)      # stand-in for tensor info / weights
    return str(path)


MODEL = [
    ("general.architecture", 8, "llama"),
    ("general.name", 8, "Tiny Test"),
    ("general.size_label", 8, "3B"),
    ("general.file_type", 4, 15),
    ("llama.context_length", 4, 8192),
    ("tokenizer.ggml.tokens", 9, (8, ["tok%d" % i for i in range(500)])),
    ("tokenizer.ggml.scores", 9, (6, [0.5] * 500)),
    ("tokenizer.chat_template", 8, "{% for m in messages %}{{ m.content }}{% endfor %}"),
]


def test_describe_reads_what_the_panel_shows(tmp_path):
    d = gm.describe(write(tmp_path / "m.gguf", MODEL))
    assert d["architecture"] == "llama" and d["name"] == "Tiny Test"
    assert d["quantization"] == "Q4_K_M" and d["context_length"] == 8192
    assert d["parameters"] == "3B" and d["chat_template"] is True
    assert d["tensors"] == 291 and d["keys"] == len(MODEL) and d["gguf_version"] == 3


def test_large_arrays_are_counted_and_the_keys_after_them_still_read(tmp_path):
    _, _, meta = gm.read_header(write(tmp_path / "m.gguf", MODEL))
    assert meta["tokenizer.ggml.tokens"] == {"array_of": 500}
    assert meta["tokenizer.ggml.scores"] == {"array_of": 500}
    # the key AFTER both skipped arrays proves the skip landed on the right byte
    assert meta["tokenizer.chat_template"].startswith("{% for")


def test_short_arrays_are_kept(tmp_path):
    _, _, meta = gm.read_header(write(tmp_path / "m.gguf", [("x.ids", 9, (4, [1, 2, 3]))]))
    assert meta["x.ids"] == [1, 2, 3]


def test_no_chat_template_reads_false(tmp_path):
    d = gm.describe(write(tmp_path / "m.gguf", MODEL[:5]))
    assert d["chat_template"] is False


def test_planted_wrong_magic(tmp_path):
    with pytest.raises(gm.NotGGUF, match="magic"):
        gm.read_header(write(tmp_path / "m.bin", MODEL, magic=b"GGML"))


def test_planted_truncated_header(tmp_path):
    p = tmp_path / "m.gguf"
    write(p, MODEL)
    p.write_bytes(p.read_bytes()[:200])
    with pytest.raises(gm.NotGGUF, match="truncated"):
        gm.read_header(str(p))


def test_planted_version_one(tmp_path):
    with pytest.raises(gm.NotGGUF, match="version"):
        gm.read_header(write(tmp_path / "m.gguf", MODEL, version=1))
