"""G-104: a package folder into the trie as module pages, with its directory
tree and its import links -- "dependencies on variables to modules to
directories". A temporary workspace; the working store is never touched."""

import pathlib
import tempfile

import pytest

from vertiscope.packages import code_tree_edges, index_package, index_tree, package_dir
from vertiscope.workspace import Workspace


@pytest.fixture()
def ws():
    with tempfile.TemporaryDirectory() as tmp:
        with Workspace(pathlib.Path(tmp) / "ws") as got:
            yield got


def _pkg(root: pathlib.Path):
    (root / "toy" / "sub").mkdir(parents=True)
    (root / "toy" / "__init__.py").write_text('"""The toy package: spins things."""\n')
    (root / "toy" / "sub" / "__init__.py").write_text('"""Helpers."""\n')
    (root / "toy" / "sub" / "wheel.py").write_text(
        '"""A wheel that spins."""\n\nRADIUS = 3\n\ndef spin(n):\n    """Turn the wheel n times."""\n    return n * RADIUS\n')
    (root / "toy" / "cart.py").write_text(
        '"""A cart with wheels."""\nfrom .sub.wheel import spin\n\ndef roll(n):\n    """Roll the cart: its wheels spin."""\n    return spin(n)\n')
    return root / "toy"


def test_the_directory_tree_hangs_modules_under_their_package():
    urls = ["code://pypi/toy/__init__.py", "code://pypi/toy/cart.py",
            "code://pypi/toy/sub/__init__.py", "code://pypi/toy/sub/wheel.py",
            "code://pypi/toy/deep/x/leaf.py"]                 # no deep/__init__ held
    got = set(code_tree_edges(urls))
    assert ("code://pypi/toy/cart.py", "code://pypi/toy/__init__.py") in got
    assert ("code://pypi/toy/sub/wheel.py", "code://pypi/toy/sub/__init__.py") in got
    assert ("code://pypi/toy/sub/__init__.py", "code://pypi/toy/__init__.py") in got
    # The nearest held package above, not a folder the store does not have.
    assert ("code://pypi/toy/deep/x/leaf.py", "code://pypi/toy/__init__.py") in got
    # The top package is a root, and no edge names a page not held.
    assert not any(c == "code://pypi/toy/__init__.py" for c, _p in got)
    assert all(c in urls and p in urls for c, p in got)


def test_a_package_folder_enters_the_store_with_its_imports(ws):
    with tempfile.TemporaryDirectory() as tmp:
        folder = _pkg(pathlib.Path(tmp))
        got = index_tree(ws, folder, "pypi/toy")
    assert got["modules"] == 4 and got["failed_n"] == 0 and got["chunks"] > 0
    pages = set(ws.store.page_urls())
    assert {"code://pypi/toy/cart.py", "code://pypi/toy/sub/wheel.py"} <= pages
    # The import is a page link: cart -> wheel (module to module).
    links = set(ws.store.page_links())
    assert ("code://pypi/toy/cart.py", "code://pypi/toy/sub/wheel.py") in links
    # And the tree over what is held.
    tree = set(code_tree_edges(pages))
    assert ("code://pypi/toy/sub/wheel.py", "code://pypi/toy/sub/__init__.py") in tree


def test_an_installed_package_is_found_and_a_missing_one_says_so(ws):
    assert package_dir("json") is not None
    assert "error" in index_package(ws, "no_such_package_vertiscope_xyz")


def test_the_page_layout_draws_the_directory_tree(ws):
    # The layout's edges carry the tree (kind "dir") for code pages; planted
    # `PLANT_NO_CODE_TREE` draws none.
    import threading
    from vertiscope.obsidian import layout
    with tempfile.TemporaryDirectory() as tmp:
        index_tree(ws, _pkg(pathlib.Path(tmp)), "pypi/toy")
    urls = list(ws.store.page_urls())

    class _Proj:
        lock = threading.Lock()
        page_pos = {u: [float(i), 0.0, 0.0] for i, u in enumerate(urls)}
        page_hsv = {}
        by_url = {u: {"c"} for u in urls}
        pos, hsv = {}, {}
        epoch, seq = 1, 1
        def status(self, _ws):
            return {}
    got = layout.projected_page_layout(ws, _Proj())
    if got is None:
        pytest.skip("this layout path needs a fitted projector")
    dirs = {(e["source"], e["target"]) for e in got["edges"] if e.get("kind") == "dir"}
    assert ("page:code://pypi/toy/sub/wheel.py", "page:code://pypi/toy/sub/__init__.py") in dirs
    layout.PLANT_NO_CODE_TREE[0] = True
    try:
        planted = layout.projected_page_layout(ws, _Proj())
        assert not any(e.get("kind") == "dir" for e in planted["edges"])
    finally:
        layout.PLANT_NO_CODE_TREE[0] = False
