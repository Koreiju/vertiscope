"""Runtime configuration for domvec.

Everything is overridable by environment variable so the CLI stays
scriptable without a config file. ``DOMVEC_HOME`` is the one that matters:
it decides where the SQLite DB, the TF-IDF index and the raw HTML archive
live (default ``~/.domvec``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    """Resolved runtime settings."""

    home: Path
    char_budget: int = 1200
    max_scrolls: int = 40
    scan_pause: float = 2.0
    max_duration: int = 45
    headless: bool = True
    page_load_timeout: int = 45
    geckodriver: str = ""
    embed_device: str = "gpu"

    # --- derived paths ---------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.home / "domvec.sqlite3"

    @property
    def index_dir(self) -> Path:
        return self.home / "tfidf_index"

    @property
    def html_dir(self) -> Path:
        return self.home / "html"

    def ensure_dirs(self) -> "Config":
        for p in (self.home, self.index_dir, self.html_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def _default_geckodriver() -> str:
    """Prefer the bundled driver, else let Selenium Manager resolve one."""
    bundled = Path(__file__).resolve().parent.parent / "drivers" / "geckodriver.exe"
    if bundled.exists():
        return str(bundled)
    return os.environ.get("DOMVEC_GECKODRIVER", "")


def load_config(home: str | os.PathLike[str] | None = None) -> Config:
    """Build a :class:`Config`, env-overridable.

    Deliberately does **not** create anything. It used to call
    :meth:`Config.ensure_dirs`, which meant that ``domvec scan`` — a command
    that writes a workspace directory and never touches SQLite — materialised
    ``~/.domvec/``, ``~/.domvec/tfidf_index/`` and ``~/.domvec/html/`` on the
    way past, because it reads this config for the geckodriver path and the
    page-load timeout. An empty store that exists is worse than one that does
    not: `domvec info` then reports on it as though it were a place the user
    had used.

    :class:`~domvec.store.Store` creates its own directories when it opens,
    which is the only moment they are needed.
    """
    resolved_home = Path(
        home
        or os.environ.get("DOMVEC_HOME")
        or (Path.home() / ".domvec")
    ).expanduser()

    cfg = Config(
        home=resolved_home,
        char_budget=_env_int("DOMVEC_CHAR_BUDGET", 1200),
        max_scrolls=_env_int("DOMVEC_MAX_SCROLLS", 40),
        scan_pause=float(os.environ.get("DOMVEC_SCAN_PAUSE", "2.0")),
        max_duration=_env_int("DOMVEC_MAX_DURATION", 45),
        headless=_env_bool("DOMVEC_HEADLESS", True),
        page_load_timeout=_env_int("DOMVEC_PAGE_LOAD_TIMEOUT", 45),
        geckodriver=os.environ.get("DOMVEC_GECKODRIVER") or _default_geckodriver(),
        embed_device=os.environ.get("DOMVEC_EMBED_DEVICE", "gpu"),
    )
    return cfg
