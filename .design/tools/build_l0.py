"""L0 capture for vertiscope: every contiguous blockquote in the authority sources
(see ../AUTHORITY.md) becomes ONE L0 artifact -- the user's granularity, one
transcribed message or paragraph -- fingerprinted by sha256 and source line.

A generator can copy the user's words exactly; it cannot read them. So every
artifact it writes is `status: stub` with the Verbatim section only; a Reading
is written by hand when the sentence is projected. Never clobbers an artifact
whose status is no longer `stub` (it has been deepened). Never writes to a
source file.

    python .design/tools/build_l0.py [--check]

--check: report sentences whose hash no longer matches its source (the user
amended the text) without writing anything.
"""
import hashlib, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESIGN = os.path.join(ROOT, ".design")
L0 = os.path.join(DESIGN, "L0-verbatim")
SOURCES = [("pg", "docs/PLUGIN_GOAL.md"), ("am", "docs/AFFINE_MAP_GOAL.md"), ("ci", "docs/CALLABLE_INTERFACE.md")]


def blocks(path):
    """(start line, heading context, exact quoted text) for each contiguous run of `>` lines."""
    heading, cur, start = "", [], 0
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines, 1):
        if line.startswith(">"):
            if not cur:
                start = i
            cur.append(line)
            continue
        if cur:
            yield start, heading, "\n".join(cur)
            cur = []
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            heading = m.group(2).strip()
    if cur:
        yield start, heading, "\n".join(cur)


def plain(quoted):
    return "\n".join(re.sub(r"^>\s?", "", l) for l in quoted.splitlines())


def status_of(path):
    try:
        with open(path, encoding="utf-8") as f:
            m = re.search(r"^status:\s*(\S+)", f.read(), re.M)
        return m.group(1) if m else None
    except FileNotFoundError:
        return None


def main(check=False):
    os.makedirs(L0, exist_ok=True)
    wrote = kept = drift = 0
    for prefix, src in SOURCES:
        for n, (line, heading, quoted) in enumerate(blocks(src), 1):
            text = plain(quoted)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            ident = "%s-%03d" % (prefix, n)
            path = os.path.join(L0, ident + ".md")
            st = status_of(path)
            if st is not None:
                with open(path, encoding="utf-8") as f:
                    old = re.search(r"^sha256:\s*(\S+)", f.read(), re.M)
                if old and old.group(1) != sha:
                    drift += 1
                    print("DRIFT", ident, src, "line", line, "(the source text changed; descendants are suspect)")
            if check or (st is not None and st != "stub"):
                kept += st is not None
                continue
            first = re.sub(r"\s+", " ", text).strip()
            title = (first[:90] + ("..." if len(first) > 90 else "")).replace("'", "’")
            body = ("---\n"
                    "id: L0.%s\nlayer: L0\ntitle: '%s'\nstatus: stub\n"
                    "source: %s\nsource_line: %d\nsha256: %s\ncontext: '%s'\n"
                    "---\n\n## Verbatim\n\n%s\n\n"
                    "## Reading\n\nNot yet read (stub): no tree projects from this sentence yet.\n"
                    ) % (ident, title, src, line, sha, heading.replace("'", "’")[:120], quoted)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            wrote += 1
    print("L0: wrote %d stubs, kept %d deepened, %d drifted" % (wrote, kept, drift))


if __name__ == "__main__":
    main(check="--check" in sys.argv)
