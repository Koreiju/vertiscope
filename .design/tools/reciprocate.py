"""Record every projection at BOTH ends: for each artifact's `projected_from`,
make sure the parent lists it in `projects_to`. Adds missing entries only; never
removes (a one-sided link is reported, not deleted -- it may be a frontier).

    python .design/tools/reciprocate.py
"""
import glob, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, ".design")


def path_of(ident):
    layer, rest = ident.split(".", 1)
    sub = {"L0": "L0-verbatim", "L1": "L1-trees", "L2": "L2-links", "L3": "L3-design",
           "L4": "L4-arch", "L5": "L5-code", "Q": "Q"}.get(layer)
    return os.path.join(D, sub, rest + ".md") if sub else None


def fm_list(text, key):
    m = re.search(r"^%s:\s*\n((?:  - .*\n)+)" % key, text, re.M)
    return [l.strip()[2:].strip() for l in m.group(1).splitlines()] if m else []


added = missing = 0
for f in glob.glob(os.path.join(D, "L*", "*.md")) + glob.glob(os.path.join(D, "Q", "*.md")):
    text = open(f, encoding="utf-8").read()
    me = re.search(r"^id:\s*(\S+)", text, re.M)
    if not me:
        continue
    me = me.group(1)
    for parent in fm_list(text, "projected_from"):
        p = path_of(parent)
        if not p or not os.path.exists(p):
            missing += 1
            print("frontier: %s names %s, which has no artifact" % (me, parent))
            continue
        pt = open(p, encoding="utf-8").read()
        if me in fm_list(pt, "projects_to"):
            continue
        if re.search(r"^projects_to:\s*\n", pt, re.M):
            pt = re.sub(r"^(projects_to:\s*\n)", r"\1  - %s\n" % me, pt, count=1, flags=re.M)
        else:
            pt = re.sub(r"^(---\n(?:.*\n)*?)(---\n)", r"\1projects_to:\n  - %s\n\2" % me, pt, count=1)
        open(p, "w", encoding="utf-8").write(pt)
        added += 1
print("reciprocal projects_to added:", added, "| frontier parents:", missing)
