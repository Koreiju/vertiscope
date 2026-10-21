"""Runtime configuration for vertiscope.

Everything is overridable by environment variable so the CLI stays
scriptable without a config file. ``VERTISCOPE_HOME`` is the one that matters:
it decides where the SQLite DB, the TF-IDF index and the raw HTML archive
live (default ``~/.vertiscope``).
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


# The realm name used when `VERTISCOPE_SANDBOX` is set to a plain truthy token
# rather than to a name of its own.
SANDBOX_DEFAULT_REALM = "vertiscope"


def _env_sandbox(name: str) -> str:
    """Resolve the sandbox knob to a realm name, or to "" for off.

    Three spellings, because the knob answers two questions at once: whether
    to use a sandbox at all, and what to call it. `1`/`true`/`on` mean "yes,
    you pick the name"; any other non-empty value *is* the name; unset or a
    falsey token means the main world, which stays the default.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw or raw.lower() in {"0", "false", "no", "off"}:
        return ""
    if raw.lower() in {"1", "true", "yes", "on"}:
        return SANDBOX_DEFAULT_REALM
    return raw


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
    # The realm the sensor is hosted in. Empty -- the default -- is the main
    # world, which is where every measurement in this repo was taken. A
    # non-empty value names a WebDriver BiDi sandbox realm to host it in
    # instead, which costs a cross-realm hop per property access and buys
    # the page not being able to find the handle. Off unless asked for.
    sandbox: str = ""

    # --- derived paths ---------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.home / "vertiscope.sqlite3"

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
    return os.environ.get("VERTISCOPE_GECKODRIVER", "")


def load_config(home: str | os.PathLike[str] | None = None) -> Config:
    """Build a :class:`Config`, env-overridable.

    Deliberately does **not** create anything. It used to call
    :meth:`Config.ensure_dirs`, which meant that ``vertiscope scan`` — a command
    that writes a workspace directory and never touches SQLite — materialised
    ``~/.vertiscope/``, ``~/.vertiscope/tfidf_index/`` and ``~/.vertiscope/html/`` on the
    way past, because it reads this config for the geckodriver path and the
    page-load timeout. An empty store that exists is worse than one that does
    not: `vertiscope info` then reports on it as though it were a place the user
    had used.

    :class:`~vertiscope.store.Store` creates its own directories when it opens,
    which is the only moment they are needed.
    """
    resolved_home = Path(
        home
        or os.environ.get("VERTISCOPE_HOME")
        or (Path.home() / ".vertiscope")
    ).expanduser()

    cfg = Config(
        home=resolved_home,
        char_budget=_env_int("VERTISCOPE_CHAR_BUDGET", 1200),
        max_scrolls=_env_int("VERTISCOPE_MAX_SCROLLS", 40),
        scan_pause=float(os.environ.get("VERTISCOPE_SCAN_PAUSE", "2.0")),
        max_duration=_env_int("VERTISCOPE_MAX_DURATION", 45),
        headless=_env_bool("VERTISCOPE_HEADLESS", True),
        page_load_timeout=_env_int("VERTISCOPE_PAGE_LOAD_TIMEOUT", 45),
        geckodriver=os.environ.get("VERTISCOPE_GECKODRIVER") or _default_geckodriver(),
        embed_device=os.environ.get("VERTISCOPE_EMBED_DEVICE", "gpu"),
        sandbox=_env_sandbox("VERTISCOPE_SANDBOX"),
    )
    return cfg
