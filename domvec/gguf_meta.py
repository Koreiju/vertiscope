"""What a GGUF file is, read from its header alone (G-381; PLUGIN_GOAL 167 g).

"functionality for generally porting in quantized GGUFs as specialized
artifacts straight from web browser scans ... where clicked download links
would then show and enter the workspace once complete as specialized
panel/cell types in themselves."

Before a model is ever run, its panel has to say what it is. GGUF keeps that
in a key-value header ahead of the tensors: `general.architecture`, the
quantisation (`general.file_type`), the context length, the chat template.
This reads the header and stops -- never the weights -- with the standard
library only (the format is llama.cpp's, MIT; its `gguf` package does the same
with more). Large arrays (a tokenizer's 150k tokens) are skipped, counted.

Nothing here downloads anything: it reads a file that is already on disk.
"""

from __future__ import annotations

import struct
from typing import Any, BinaryIO, Dict, Optional, Tuple

MAGIC = b"GGUF"

# value types, from the GGUF specification
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f",
           7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9

# general.file_type -> llama.cpp's name for the quantisation (llama.h, LLAMA_FTYPE_*)
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
              10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S",
              15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS",
              20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S",
              25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M",
              30: "IQ4_XS", 31: "IQ1_M", 32: "BF16"}

ARRAY_KEEP = 64            # arrays longer than this are counted, not kept


class NotGGUF(ValueError):
    pass


def _read(f: BinaryIO, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise NotGGUF("truncated header: wanted %d bytes, got %d" % (n, len(b)))
    return b


def _u(f: BinaryIO, fmt: str) -> Any:
    return struct.unpack(fmt, _read(f, struct.calcsize(fmt)))[0]


def _string(f: BinaryIO) -> str:
    n = _u(f, "<Q")
    if n > 1 << 26:
        raise NotGGUF("implausible string length %d" % n)
    return _read(f, n).decode("utf-8", "replace")


def _value(f: BinaryIO, t: int) -> Any:
    if t in _SCALAR:
        return _u(f, _SCALAR[t])
    if t == _STRING:
        return _string(f)
    if t == _ARRAY:
        et, n = _u(f, "<I"), _u(f, "<Q")
        if et == _ARRAY:
            raise NotGGUF("nested arrays are not read")
        if n <= ARRAY_KEEP:
            return [_value(f, et) for _ in range(n)]
        if et in _SCALAR:
            f.seek(struct.calcsize(_SCALAR[et]) * n, 1)
        else:
            for _ in range(n):
                _value(f, et)
        return {"array_of": n}
    raise NotGGUF("unknown value type %d" % t)


def read_header(path: str) -> Tuple[int, int, Dict[str, Any]]:
    """(version, tensor count, metadata) from the file's header."""
    with open(path, "rb") as f:
        if _read(f, 4) != MAGIC:
            raise NotGGUF("not a GGUF file (magic is not 'GGUF')")
        version = _u(f, "<I")
        if version < 2:
            raise NotGGUF("GGUF version %d predates 64-bit counts" % version)
        tensors, kvs = _u(f, "<Q"), _u(f, "<Q")
        meta: Dict[str, Any] = {}
        for _ in range(kvs):
            k = _string(f)
            meta[k] = _value(f, _u(f, "<I"))
        return version, tensors, meta


def describe(path: str) -> Dict[str, Optional[Any]]:
    """What the model's panel shows before anything runs it."""
    version, tensors, meta = read_header(path)
    arch = meta.get("general.architecture")
    ft = meta.get("general.file_type")
    tpl = meta.get("tokenizer.chat_template")
    return {
        "name": meta.get("general.name"),
        "architecture": arch,
        "quantization": FILE_TYPES.get(ft, ft) if ft is not None else None,
        "context_length": meta.get("%s.context_length" % arch) if arch else None,
        "parameters": meta.get("general.size_label"),
        "chat_template": bool(tpl) if tpl is not None else False,
        "gguf_version": version,
        "tensors": tensors,
        "keys": len(meta),
    }


def main(argv=None) -> int:
    """`python -m domvec.gguf_meta FILE...` -- each file's description as JSON."""
    import json
    import sys
    paths = list(sys.argv[1:] if argv is None else argv)
    for p in paths:
        try:
            print(json.dumps({"path": p, **describe(p)}))
        except (OSError, NotGGUF) as e:
            print(json.dumps({"path": p, "error": str(e)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
