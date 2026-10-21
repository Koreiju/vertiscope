import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def catalog_html() -> str:
    return (FIXTURES / "catalog.html").read_text(encoding="utf-8")


@pytest.fixture()
def cfg(tmp_path):
    """A Config rooted in a throwaway dir so tests never touch ~/.vertiscope."""
    from vertiscope.config import load_config

    return load_config(tmp_path / "home")


@pytest.fixture()
def store(cfg):
    from vertiscope.store import Store

    with Store(cfg) as st:
        yield st
