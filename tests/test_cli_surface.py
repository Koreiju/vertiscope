"""The command line says which store it is talking about.

Two stores are reachable from one `vertiscope` command. The address-trie pipeline
writes a *workspace* — a directory holding `graph.kuzu`, `freq/` and
`chunks/*.jsonl`. An earlier single-snapshot pipeline writes a *home* — SQLite
under `~/.vertiscope`. On a machine with twenty scanned pages:

    vertiscope status          20 pages · 3,012 chunks · 42,346 addresses
    vertiscope ls              nothing scraped yet
    vertiscope info            pages 0 · instances 0 · indexed_rows 0

Each was telling the truth about the store it read and lying about the
machine. `purge --all` was the dangerous one: "purged everything (0
instances)" after deleting nothing the user had, which is how someone comes to
believe a corpus is gone while it is still on disk — and there was no way at
all to clear a workspace from the command line.

The obvious repair — delete the earlier pipeline's commands — is wrong, and
these tests exist partly to record why. `ls`, `info`, `show` and `search`
*are* the observation alphabet that `scripts/audit_observables.py` measures
and that COR-10.7 reasons about: `test_model_obligations` asserts position
escapes through `show` and through nothing else. Removing a surface shrinks
that alphabet, which by COR-10.7 is a semantic change to the identity analysis
in MODEL §8.3 — not a tidy-up.

So the fix is narrow. What a command *reports about stored content* on stdout
is untouched. What changes is that the store gets named, on stderr, where
advice belongs; and `purge` can address the workspace.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope.cli import build_parser, main  # noqa: E402

# Commands reading the earlier single-snapshot store. Not deprecated: they are
# the measured observation alphabet (COR-10.7). They must say so.
HOME_STORE_COMMANDS = {"scrape", "search", "shell", "ls", "show", "info",
                       "chunk"}


def _subcommands():
    parser = build_parser()
    action = next(a for a in parser._actions if a.dest == "command")
    return action.choices


# --- the two families stay distinguishable --------------------------------


def test_every_subcommand_belongs_to_exactly_one_store():
    """A command addresses the workspace or the home store, never neither.

    Structural rather than behavioural, because the failure it catches is a
    command *added* against a third place, which no existing test would see.
    """
    stray = []
    for name, sub in _subcommands().items():
        flags = {opt for action in sub._actions for opt in action.option_strings}
        workspace = "--workspace" in flags
        home = name in HOME_STORE_COMMANDS
        if workspace == home:  # both or neither
            stray.append(name)
    assert not stray, (
        f"subcommands addressing both stores or no store: {stray}")


def test_home_store_commands_name_their_store(tmp_path, capsys):
    """`ls` on an empty home store must not read as "nothing on this machine".

    The name goes to stderr so the stdout surface COR-10.7 reasons about is
    byte-identical to what it was.
    """
    for argv in (["--home", str(tmp_path / "home"), "ls"],
                 ["--home", str(tmp_path / "home"), "info"]):
        main(argv)
        captured = capsys.readouterr()
        assert str(tmp_path / "home") in captured.err, (
            f"`{argv[-1]}` does not say which store it read: {captured.err!r}")


def test_naming_the_store_does_not_change_what_a_command_reports(tmp_path,
                                                                 capsys):
    """The COR-10.7 guard: stdout is advice-free.

    `scripts/audit_layout_sensitivity.py` compares these surfaces across ingest
    permutations and `test_model_obligations` asserts what may appear in them.
    A hint on stdout would enter both.
    """
    main(["--home", str(tmp_path / "home"), "ls"])
    out = capsys.readouterr().out
    assert "workspace" not in out.lower()
    assert "vertiscope status" not in out


def test_an_empty_home_store_points_at_a_workspace_that_has_content(
        tmp_path, capsys, monkeypatch):
    """The actual defect: "nothing scraped yet" beside a full workspace."""
    fixture = ROOT / "tests" / "fixtures" / "catalog.html"
    monkeypatch.chdir(tmp_path)
    assert main(["index", str(fixture), "-w", "build"]) == 0
    capsys.readouterr()

    main(["--home", str(tmp_path / "home"), "ls"])
    err = capsys.readouterr().err
    assert "build" in err and "status" in err, (
        f"`ls` reported an empty machine beside a populated workspace: {err!r}")


# --- purge reaches the store the scan wrote -------------------------------


def test_purge_empties_the_workspace_it_names(tmp_path, capsys):
    from vertiscope.workspace import Workspace

    fixture = ROOT / "tests" / "fixtures" / "catalog.html"
    workspace = tmp_path / "ws"

    assert main(["index", str(fixture), "-w", str(workspace)]) == 0
    with Workspace(workspace) as ws:
        assert ws.stats()["chunks"] > 0

    assert main(["purge", "-w", str(workspace), "--all", "--yes"]) == 0
    capsys.readouterr()

    with Workspace(workspace) as ws:
        after = ws.stats()
    assert after["chunks"] == 0, "purge reported success and deleted nothing"
    assert after["addresses"] == 0
    assert not list((workspace / "chunks").glob("*.jsonl"))


def test_purge_one_url_leaves_the_others(tmp_path, capsys):
    from vertiscope.workspace import Workspace

    fixture = ROOT / "tests" / "fixtures" / "catalog.html"
    workspace = tmp_path / "ws"

    main(["index", str(fixture), "-w", str(workspace), "--url",
          "https://a.test/one"])
    main(["index", str(fixture), "-w", str(workspace), "--url",
          "https://b.test/two"])
    capsys.readouterr()

    assert main(["purge", "-w", str(workspace), "--url",
                 "https://a.test/one", "--yes"]) == 0
    capsys.readouterr()

    with Workspace(workspace) as ws:
        assert ws.pages() == ["https://b.test/two"]
        assert ws.stats()["chunks"] > 0


def test_purge_refuses_without_confirmation(tmp_path, capsys):
    """Destructive by default is the wrong default for a whole corpus."""
    from vertiscope.workspace import Workspace

    fixture = ROOT / "tests" / "fixtures" / "catalog.html"
    workspace = tmp_path / "ws"
    main(["index", str(fixture), "-w", str(workspace)])
    capsys.readouterr()

    assert main(["purge", "-w", str(workspace), "--all"]) != 0

    with Workspace(workspace) as ws:
        assert ws.stats()["chunks"] > 0


def test_purge_on_a_missing_workspace_does_not_create_one(tmp_path, capsys):
    """A mistyped path must not report success over a workspace it just made."""
    missing = tmp_path / "typo"
    assert main(["purge", "-w", str(missing), "--all", "--yes"]) != 0
    assert not (missing / "graph.kuzu").exists()


def test_purge_can_still_reach_the_home_store(tmp_path, capsys):
    """The earlier store stays clearable — it is still written by `scrape`."""
    assert main(["--home", str(tmp_path / "home"), "purge", "--home-store",
                 "--all", "--yes"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "home") in out or "home" in out.lower()


# --- the tool accepts its own output ---------------------------------------


def _indexed(tmp_path):
    fixture = ROOT / "tests" / "fixtures" / "catalog.html"
    workspace = tmp_path / "ws"
    assert main(["index", str(fixture), "-w", str(workspace),
                 "--url", "https://x.test/catalog"]) == 0
    return workspace


def test_an_address_printed_by_find_can_be_handed_back_to_where(tmp_path,
                                                                capsys):
    """The address is the one output type, and nothing used to accept one.

    `find --addresses` printed addresses and `browse`'s `where` printed
    addresses; neither form could be given to anything, so the singular
    output type was write-only. This drives the loop end to end: run a
    query, take an id out of the output, feed it back in.
    """
    workspace = _indexed(tmp_path)
    capsys.readouterr()

    assert main(["find", "book", "-w", str(workspace), "-k", "1",
                 "--addresses", "--floor", "1e-6"]) == 0
    printed = capsys.readouterr().out

    aids = [word for line in printed.splitlines() for word in line.split()
            if len(word) == 16 and all(c in "0123456789abcdef" for c in word)]
    assert aids, f"find --addresses printed no id to feed back:\n{printed}"

    assert main(["where", aids[0], "-w", str(workspace)]) == 0
    resolved = capsys.readouterr().out
    assert aids[0] in resolved
    assert "xpath" in resolved and "chunk" in resolved


def test_where_accepts_all_three_spellings(tmp_path, capsys):
    """aid, full key, absolute xpath — the three forms the tool emits."""
    from vertiscope.workspace import Workspace

    workspace = _indexed(tmp_path)
    capsys.readouterr()

    with Workspace(workspace) as ws:
        cid = ws.store.chunks()[0].cid
        address, _value = ws.store.addresses_of(cid)[0]

    for spelling in (address.aid, address.key(), address.xpath):
        assert main(["where", spelling, "-w", str(workspace)]) == 0, spelling
        out = capsys.readouterr().out
        assert address.xpath in out, f"{spelling!r} did not resolve"


def test_where_reports_a_miss_rather_than_inventing_one(tmp_path, capsys):
    workspace = _indexed(tmp_path)
    capsys.readouterr()
    assert main(["where", "deadbeefdeadbeef", "-w", str(workspace)]) == 1
    assert "no address" in capsys.readouterr().out


def test_where_shows_every_address_at_an_element(tmp_path, capsys):
    """An xpath names an element, and an element carries several addresses.

    Its text, its href, each `srcset` candidate — returning one would be
    choosing silently between them.
    """
    from vertiscope.workspace import Workspace

    workspace = _indexed(tmp_path)
    capsys.readouterr()

    with Workspace(workspace) as ws:
        counts = {}
        for chunk in ws.store.chunks():
            for address, _v in ws.store.addresses_of(chunk.cid):
                counts.setdefault(address.xpath, set()).add(address.aid)
        shared = [x for x, aids in counts.items() if len(aids) > 1]

    if not shared:
        pytest.skip("no element in the fixture carries two addresses")
    assert main(["where", shared[0], "-w", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "addresses at that element" in out


# --- one flag, one meaning -------------------------------------------------


def test_global_verbose_survives_the_subcommand():
    """`vertiscope -v <cmd>` set verbose, then the subparser reset it to False.

    argparse copies a subparser's defaults over the namespace the parent
    already filled, so a subcommand defining its own `--verbose` silently
    undid the global one — and `main` reads exactly that attribute to choose
    the log level. One flag, two meanings, and the outer one lost.
    """
    parser = build_parser()
    for name in _subcommands():
        args = _parse_smallest(parser, name, prefix=["-v"])
        if args is None:
            continue
        assert getattr(args, "verbose", False) is True, (
            f"`vertiscope -v {name}` lost the global --verbose flag")


def test_verbose_also_works_after_the_subcommand():
    parser = build_parser()
    for name in _subcommands():
        args = _parse_smallest(parser, name, prefix=[], suffix=["-v"])
        if args is None:
            continue
        assert getattr(args, "verbose", False) is True, (
            f"`vertiscope {name} -v` does not set --verbose")


def _parse_smallest(parser, name, prefix, suffix=()):
    """Parse `name` with the fewest arguments that satisfy it, or None."""
    sub = _subcommands()[name]
    positionals = [
        a for a in sub._actions
        if not a.option_strings and a.dest != "help"
    ]
    argv = list(prefix) + [name]
    for action in positionals:
        if action.nargs in ("?", "*"):
            continue
        argv.append("x")
    argv += list(suffix)
    try:
        return parser.parse_args(argv)
    except SystemExit:
        return None


@pytest.mark.parametrize("name", sorted(HOME_STORE_COMMANDS))
def test_the_observation_alphabet_is_intact(name):
    """COR-10.7: removing a surface is a semantic change, not a tidy-up.

    `search`, `show`, `ls` and `info` are what `audit_observables.py` measures
    and what MODEL §8.3's identity analysis is stated against. Each has a
    workspace-side counterpart under a different name, which makes them look
    redundant; they are not, and this records that so the next person tempted
    to delete them reads the reason first.
    """
    assert name in _subcommands()
