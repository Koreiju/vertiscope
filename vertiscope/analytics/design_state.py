"""What is built, what is not, and what nobody has looked at yet.

    python -m vertiscope.analytics.design_state

**It lived in `build_sweep/` and that directory is GITIGNORED**, so the one
script `CLAUDE.md` names as the reporting mechanism was not in version
control and would not have survived a clone. Constraint 3 is explicit that
analytics live in `vertiscope/analytics/` and write their artifacts to
`build_analytics/`; this is the second half of that sentence being obeyed
while the first half was not.

Writes `build_analytics/design_state.md`, regenerated on every change, never
edited by hand. The DIFF of that file is what a reader checks: it says which
requirements moved and what evidence moved them.

**Generated rather than maintained, because maintained is what failed.** The
PRD's status column is written by whoever last touched a row, and in one week
it drifted sixteen rows -- forty-seven read "Open" when thirty-one of them had
shipped. A column that is computed cannot drift, and the cost of that is that
the row has to say where its evidence IS.

**Which is the second thing this measures.** Of 223 requirement rows, 76 are
marked done and 18 of those cite a file, a probe, a test or a measurement
section. The other 58 are claims with nothing attached -- true or false, there
is no way to tell from the document, and no way for a reader to check one
without reading the whole repository. Every unevidenced "Done" is listed here
as such, which is the only pressure that makes the citation get written.

**And a status the PRD does not have: `Confirm`.** Between "I built it and
measured it" and "you have seen it work" there is a real gap, and it has been
filled with silence. A row that is code-complete and verified by test or probe
but has not been looked at in the running app is `Confirm`, and it stays there
until a human says otherwise. The unfold edges sit in exactly that state right
now, blocked on a debug port.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PRD = ROOT / "docs" / "PLUGIN_PRD.md"
GOALS = [ROOT / "docs" / "PLUGIN_GOAL.md",
         ROOT / "docs" / "AFFINE_MAP_GOAL.md"]
OUT = ROOT / "build_analytics" / "design_state.md"

#: A requirement row: `| TAG | what it asks | the verdict |`.
ROW = re.compile(r"^\|\s*([A-Z]+-[A-Z]?\d+)\s*\|(.*?)\|(.*)\|\s*$")

#: What a verdict opens with, and what that means. Ordered: the first match
#: wins, so `Partly` is tested before the bare `Part`ial spellings.
#: `defect` is its own state, not a kind of open. Section 0 of the PRD is
#: explicit that several rows are SHIPPED CODE CONTRADICTING THE GOAL, which
#: is a different and more urgent thing than work not yet begun, and counting
#: the two together hides the urgent one inside the large one.
#: `standing` is not work. `X-*` are principles the work is held to -- "every
#: metric gets a non-vacuity test" does not get DONE -- and counting them as
#: open made the backlog five rows longer than it is.
#:
#: The openers are matched against a verdict that usually carries a date and
#: a clause after it, so they are PREFIXES: `**Done**` does not match
#: `**Done 2026-09-12**`, which is how four fixed rows sat in "cannot read"
#: while reading perfectly well to a person.
STATUSES = [
    #: A requirement answered the OTHER way. `P-B3` asked to embed a
    #: Selenium window and the sensor moved into Electron instead, so there
    #: is no window left to embed. Neither done nor open: counting it open
    #: would keep asking for work nobody should do, and counting it done
    #: would claim something that was never built.
    ("superseded", ("**Superseded", "Superseded")),
    ("standing", ("Standing", "**Standing")),
    ("defect", ("**Defect", "Defect")),
    ("done", ("**Done", "Done", "**FIXED", "FIXED", "**Fixed", "Fixed",
              "**Verdict delivered", "**Available", "**Measured",
              "**Delivered", "**Built and measured", "**Answered",
              "**Shipped", "**Holds")),
    ("confirm", ("**Confirm", "Confirm")),
    ("partly", ("**Partly", "Partial", "**Partial", "**Built", "**Wired",
                "By design", "**By design")),
    ("open", ("Open", "**Open", "Verify", "**Verify", "Not ", "**Not ",
              "Deferred", "**Deferred")),
]

#: Things a verdict can point at, in descending order of how checkable they
#: are. A path either exists or it does not; a section reference can be
#: resolved in the document; prose can be neither.
#: `.mjs` was missing, so every citation of `confirm.mjs` -- the file that
#: holds the live checks -- read as "cites nothing". The count of unevidenced
#: rows is the one number this file exists to apply pressure with, and it was
#: overstating itself by the whole live-confirmation surface.
CITES = re.compile(r"`([^`]+\.(?:py|ts|js|mjs|md|json))`|§([MNO]\.\d+)"
                   r"|\b(probes/[\w.-]+\.js)\b|\b(tests/test_[\w.-]+\.py)\b")


#: Every file in the repository, by basename, built once. Cheaper than a
#: filesystem walk per citation and it is what makes the check exact.
_TREE = None


def _exists(target: str) -> bool:
    global _TREE
    if _TREE is None:
        _TREE = set()
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                _TREE.add(path.name)
                try:
                    _TREE.add(path.relative_to(ROOT).as_posix())
                except ValueError:
                    pass
    name = target.rsplit("/", 1)[-1]
    return target in _TREE or name in _TREE


def classify(verdict: str) -> str:
    text = verdict.strip()
    for name, openers in STATUSES:
        for opener in openers:
            if text.startswith(opener):
                return name
    return "unstated"


def evidence(verdict: str, sections: set) -> tuple:
    """What this verdict points at, and which of those pointers is broken.

    A citation to a file that no longer exists is worse than no citation: it
    reads as proof and is a dangling reference. They are listed separately.
    """
    found, broken = [], []
    for match in CITES.finditer(verdict):
        path, section, probe, test = match.groups()
        target = path or probe or test
        if target:
            # By basename anywhere in the tree, not by three guessed prefixes.
            # Guessing reported `graph.ts` missing five times over while it
            # sat in `obsidian-plugin/src/` -- and a checker that cries wolf
            # is worse than no checker, because the next real dangling
            # citation is read as another false alarm.
            if _exists(target):
                found.append(target)
            else:
                broken.append(target)
        elif section:
            (found if section in sections else broken).append("§" + section)
    return found, broken


def main() -> int:
    if not PRD.exists():
        print("no PRD at", PRD)
        return 2
    text = PRD.read_text(encoding="utf-8")
    sections = set(re.findall(r"^### ([MNO]\.\d+)", text, re.M))

    rows = []
    for line in text.split("\n"):
        hit = ROW.match(line)
        if not hit:
            continue
        tag, asks, verdict = hit.group(1), hit.group(2), hit.group(3)
        # The verdict is the LAST cell; a requirement containing a pipe would
        # otherwise split into three and be read as its own explanation.
        cells = line.split(" | ")
        verdict = cells[-1].rstrip("| ").strip() if len(cells) > 2 else verdict
        found, broken = evidence(verdict, sections)
        rows.append({
            "tag": tag,
            "asks": re.sub(r"\*\*", "", asks).strip(),
            "status": classify(verdict),
            "verdict": verdict.strip(),
            "cites": found,
            "broken": broken,
        })

    by_status = Counter(r["status"] for r in rows)
    by_prefix = defaultdict(Counter)
    for r in rows:
        by_prefix[r["tag"].split("-")[0]][r["status"]] += 1

    unevidenced = [r for r in rows if r["status"] == "done" and not r["cites"]]
    dangling = [r for r in rows if r["broken"]]
    awaiting = [r for r in rows if r["status"] == "confirm"]
    open_rows = [r for r in rows if r["status"] in ("open", "partly")]
    unstated = [r for r in rows if r["status"] == "unstated"]

    try:
        head = subprocess.run(["git", "log", "-1", "--format=%h %ad %s",
                               "--date=format:%Y-%m-%d"],
                              cwd=ROOT, capture_output=True, text=True,
                              check=False).stdout.strip()
    except Exception:                                   # noqa: BLE001
        head = "(git unavailable)"

    lines = []
    add = lines.append
    add("# Design state")
    add("")
    add("*Generated by `vertiscope/analytics/design_state.py`. Do not edit — edit "
        "the PRD and regenerate.*")
    add("")
    add("HEAD: `%s`" % head)
    add("")
    add("## Where it stands")
    add("")
    add("| | rows |")
    add("|---|---|")
    for name in ("done", "confirm", "partly", "open", "defect", "superseded",
                 "standing", "unstated"):
        if by_status.get(name):
            add("| %s | %d |" % (name, by_status[name]))
    add("| **total** | **%d** |" % len(rows))
    add("")
    add("| family | done | confirm | partly | open | defect | superseded | "
        "standing | unstated |")
    add("|---|---|---|---|---|---|---|---|---|")
    for prefix in sorted(by_prefix):
        c = by_prefix[prefix]
        add("| %s-* | %d | %d | %d | %d | %d | %d | %d | %d |"
            % (prefix, c["done"], c["confirm"], c["partly"], c["open"],
               c["defect"], c["superseded"], c["standing"], c["unstated"]))
    add("")

    defects = [r for r in rows if r["status"] == "defect"]
    if defects:
        add("## Defects — shipped code that contradicts the goal")
        add("")
        add("Not a backlog. These are things the application DOES that the "
            "goal says it should not, which is why section 0 of the PRD puts "
            "them before everything that is merely unbuilt.")
        add("")
        for r in defects:
            add("- `%s` — %s" % (r["tag"], r["asks"][:96]))
        add("")

    add("## Claims with nothing attached")
    add("")
    add("Rows marked done that cite no file, probe, test or measurement "
        "section. Each is a claim a reader cannot check without reading the "
        "repository, and the reason the status column could drift sixteen "
        "rows in a week without anyone noticing.")
    add("")
    if unevidenced:
        add("**%d of %d done rows.**" % (len(unevidenced), by_status["done"]))
        add("")
        for r in unevidenced:
            add("- `%s` — %s" % (r["tag"], r["asks"][:96]))
    else:
        add("None. Every done row points at something.")
    add("")

    if dangling:
        add("## Citations that do not resolve")
        add("")
        add("Worse than no citation: these read as proof and point at "
            "nothing.")
        add("")
        for r in dangling:
            add("- `%s` — missing %s" % (r["tag"], ", ".join(r["broken"])))
        add("")

    add("## Waiting on a human")
    add("")
    add("Built and verified by test or probe, but not yet seen working in "
        "the running app by anyone. This is the state between *measured* and "
        "*believed*, and nothing leaves it without a person saying so.")
    add("")
    if awaiting:
        for r in awaiting:
            add("- `%s` — %s" % (r["tag"], r["asks"][:96]))
    else:
        add("Nothing queued.")
    add("")

    add("## Still to build")
    add("")
    for prefix in sorted({r["tag"].split("-")[0] for r in open_rows}):
        family = [r for r in open_rows if r["tag"].startswith(prefix + "-")]
        if not family:
            continue
        add("### %s-* (%d)" % (prefix, len(family)))
        add("")
        for r in family:
            mark = "~" if r["status"] == "partly" else " "
            add("- `%s`%s %s" % (r["tag"], mark, r["asks"][:100]))
        add("")
    add("`~` marks a row that is partly done: something exists and it is not "
        "finished.")
    add("")

    if unstated:
        add("## Verdicts this cannot read")
        add("")
        add("A verdict that opens with none of the known words. Either the "
            "row needs rewording or this script needs to learn it — and "
            "either way the row is invisible to every count above.")
        add("")
        for r in unstated:
            add("- `%s` — %s" % (r["tag"], (r["verdict"] or "(empty)")[:90]))
        add("")

    # What has actually been SEEN working, as opposed to claimed.
    live_path = ROOT / "build_analytics" / "live_confirmations.json"
    add("## Seen working in the running application")
    add("")
    add("From `build_analytics/live_confirmations.json`, merged by "
        "requirement from every run that drives the loaded plugin and a "
        "running sidecar (`vertiscope/obsidian/confirmations.py`). A status column can only drift from what "
        "the DOCUMENT says; this is the drift that matters. `G-6` sat in "
        "`Confirm` citing 31 nodes and 30 edges, and live it was 26 and 0.")
    add("")
    if live_path.exists():
        import json
        blob = json.loads(live_path.read_text(encoding="utf-8"))
        rows_seen = blob.get("results", [])
        ok = [r for r in rows_seen if r.get("pass")]
        fresh = [r for r in rows_seen if str(r.get("store", "")).startswith("fresh")]
        add("Each requirement's LATEST verdict — %d of %d pass; %d read off a "
            "fresh store the run seeded itself, %d off the working one."
            % (len(ok), len(rows_seen), len(fresh), len(rows_seen) - len(fresh)))
        add("")
        for r in rows_seen:
            add("- `%s` %s — %s *(%s, %s)*"
                % (r["id"], "PASS" if r.get("pass") else "**FAIL**",
                   r.get("asks", "")[:80], r.get("when", "?"),
                   r.get("store", "?")))
        add("")
        have = {r["id"] for r in rows_seen}
        missing = [r for r in rows
                   if r["status"] in ("done", "confirm") and r["tag"] not in have]
        add("**%d rows are marked done or confirm with no live check.** That "
            "is the honest denominator: they may work, and nothing here says "
            "so." % len(missing))
    else:
        add("No run recorded. `python -m vertiscope.obsidian fresh` writes one.")
    add("")

    add("## Where the verbatim record ends")
    add("")
    for goal in GOALS:
        if not goal.exists():
            continue
        body = goal.read_text(encoding="utf-8")
        marks = re.findall(r"^#{2,3} (Addendum[^\n]*|The user's statement[^\n]*)",
                           body, re.M)
        stamp = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=format:%Y-%m-%d",
             "--", str(goal.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        add("**`%s`** — last committed %s"
            % (goal.relative_to(ROOT).as_posix(), stamp or "?"))
        for m in marks:
            add("  - %s" % m)
        add("")
    add("Every requirement above is a DECOMPOSITION of those statements. "
        "Where the record ends, the requirements below it are interpretation "
        "with nothing to be checked against.")
    add("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote %s" % OUT.relative_to(ROOT).as_posix())
    print("  %d rows: %s" % (len(rows),
                             ", ".join("%s %d" % (k, v)
                                       for k, v in by_status.most_common())))
    print("  %d done rows cite nothing" % len(unevidenced))
    if dangling:
        print("  %d rows cite something that is not there" % len(dangling))
    return 0


if __name__ == "__main__":
    sys.exit(main())
