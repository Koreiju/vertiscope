"""Selenium Firefox session management.

Differences from the ``web_fiber_haptics`` original (``selenium_client.py``):

* **Not a singleton.** It's a context manager, so a CLI invocation owns its
  browser and always tears it down — no cross-request driver reuse, no
  process leak when a scan raises.
* **Headless by default.** The original forced headful because a human drove
  the browser; here nobody is watching. ``--headful`` re-enables it.
* Stale profile-lock clearing is kept — it is the single most common cause
  of "geckodriver: process unexpectedly closed with status 0".
"""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService

from .config import Config

logger = logging.getLogger(__name__)

_LOCK_FILES = ("parent.lock", ".parentlock", "lock")


class BrowserError(RuntimeError):
    """Raised when a WebDriver session cannot be established."""


def clear_stale_profile_locks(profile_path: str | os.PathLike[str]) -> list[str]:
    """Delete Firefox profile locks left behind by a killed browser.

    Returns the names cleared. A ``PermissionError`` means a live Firefox
    still holds the profile — we leave that alone rather than kill someone's
    open window.
    """
    cleared: list[str] = []
    for fname in _LOCK_FILES:
        p = Path(profile_path) / fname
        try:
            if not p.exists() and not p.is_symlink():
                continue
            p.unlink()
            cleared.append(fname)
        except PermissionError:
            logger.warning("profile lock %s held by a live process", p)
        except OSError:
            continue
    return cleared


def _resolve_firefox_binary() -> Optional[str]:
    """Locate firefox.exe: env override, then the usual Windows install dirs."""
    env = os.environ.get("VERTISCOPE_FIREFOX_BINARY")
    if env and Path(env).exists():
        return env
    for candidate in (
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "/usr/bin/firefox",
        "/usr/local/bin/firefox",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("firefox")


def build_driver(cfg: Config, headless: Optional[bool] = None, *,
                 bidi: Optional[bool] = None,
                 prefs: Optional[dict] = None) -> webdriver.Firefox:
    """Construct a Firefox WebDriver honouring ``cfg``.

    ``bidi`` asks for a WebDriver BiDi websocket alongside the classic
    session, which is what hosting the sensor in a sandbox realm needs. It
    defaults to whether ``cfg.sandbox`` names one, and it is the *only*
    thing that flag changes here: no preference is added, removed or
    altered by it, because the profile is a measuring instrument and a
    corpus read under two different profiles is two corpora.

    ``prefs`` is the deliberate exception, and it exists so that "two
    corpora" can be *measured* rather than only warned about. Hardening the
    browser against being tracked changes the profile, which may change what
    the page does and therefore what the fold sees; `analytics.anonymity`
    passes an arm's preferences here and diffs the result against the
    baseline, so the fidelity cost of each measure is a number instead of an
    argument. Nothing in the ordinary path supplies it.
    """
    use_headless = cfg.headless if headless is None else headless

    options = Options()
    if use_headless:
        options.add_argument("-headless")
    # Quieter, more deterministic scraping surface.
    options.set_preference("browser.cache.disk.enable", False)
    options.set_preference("browser.sessionstore.resume_from_crash", False)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("media.volume_scale", "0.0")
    options.set_preference("app.update.auto", False)
    options.set_preference("datareporting.healthreport.uploadEnabled", False)

    # Applied last so an arm can override a default above rather than fight
    # it, and only ever supplied by the harness that measures the cost.
    for name, value in (prefs or {}).items():
        options.set_preference(name, value)

    if bidi is None:
        bidi = bool(getattr(cfg, "sandbox", ""))
    if bidi:
        # `webSocketUrl: true`. A capability, not a preference — it asks
        # geckodriver for the BiDi endpoint and leaves the profile alone.
        options.enable_bidi = True

    binary = _resolve_firefox_binary()
    if binary:
        options.binary_location = binary

    service_kwargs = {"log_output": os.devnull}
    if cfg.geckodriver and Path(cfg.geckodriver).exists():
        service_kwargs["executable_path"] = cfg.geckodriver

    try:
        driver = webdriver.Firefox(
            options=options, service=FirefoxService(**service_kwargs)
        )
    except Exception as exc:  # noqa: BLE001 - surface a usable message
        raise BrowserError(
            f"could not start Firefox ({type(exc).__name__}: {exc}). "
            "Check that Firefox is installed, and that no stale geckodriver "
            "process is holding the profile."
        ) from exc

    driver.set_page_load_timeout(cfg.page_load_timeout)
    driver.set_script_timeout(cfg.page_load_timeout)
    return driver


@contextmanager
def browser_session(
    cfg: Config, headless: Optional[bool] = None, *,
    bidi: Optional[bool] = None, prefs: Optional[dict] = None
) -> Iterator[webdriver.Firefox]:
    """Own a Firefox driver for the duration of the block, always quitting it.

    `prefs` is passed through to `build_driver` and exists only so the
    anonymity harness can measure what a hardened profile costs the fold.
    """
    driver = build_driver(cfg, headless=headless, bidi=bidi, prefs=prefs)
    try:
        yield driver
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001 - teardown must never mask the real error
            logger.debug("driver.quit() failed during teardown", exc_info=True)
