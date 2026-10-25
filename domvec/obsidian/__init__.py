"""Bridge from the distiller to an Obsidian vault.

The vault is a SECOND rendering of the same store, not a copy of it. Every
note it writes is derived from a `StoredChunk`, carries that chunk's `cid` in
its frontmatter, and can be regenerated; nothing in the vault is a source of
truth that the graph store does not already hold.

One constraint governs the whole module. `Workspace.mirror_path` names its
files by digest on purpose -- "a listing that names the pages is the browsing
history in plain sight" -- and a vault is exactly the opposite: a listable
directory of readable names, displayed by name in the graph view. Exporting
therefore REVERSES a deliberate privacy decision, so it is opt-in and scoped
to an explicitly chosen set of pages. It never walks the whole workspace by
default. See `export_vault`.
"""

__all__ = ["VaultExport", "export_vault"]


def __getattr__(name):
    # Lazily: importing the package must not load the store (`graphstore`:
    # kuzu, numpy). `python -m domvec.obsidian supervise` imports this package,
    # and the supervisor -- whose only work is starting and watching a child --
    # carried numpy's and scipy's OpenBLAS (117 modules, 53 threads) because
    # of this line (2026-10-25).
    if name in __all__:
        from . import export
        return getattr(export, name)
    raise AttributeError(name)
