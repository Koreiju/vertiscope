"""P-N4: the vault facade a note's kernel gets (`kernel_objects.vault_boot`)."""

import os

import pytest

from domvec.obsidian.kernel_objects import VAULT_DONE, vault_boot


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "lab").mkdir()
    (tmp_path / "lab" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    cwd = os.getcwd()
    ns = {}
    exec(vault_boot(str(tmp_path), "lab/notebook.md"), ns)
    yield tmp_path, ns
    os.chdir(cwd)


def test_the_kernel_runs_in_its_notes_folder(vault):
    root, ns = vault
    assert os.getcwd() == str((root / "lab").resolve())
    assert open("data.csv", encoding="utf-8").read().startswith("a,b")
    assert ns["Vault"].ls() == ["data.csv"]
    assert ns["Vault"].ls("/") == ["lab/"]


def test_a_write_lands_in_the_vault(vault):
    root, ns = vault
    assert ns["Vault"].write("out/result.md", "# made") == "lab/out/result.md"
    assert (root / "lab" / "out" / "result.md").read_text(encoding="utf-8") == "# made"
    assert ns["Vault"].glob("*.csv") == ["lab/data.csv"]


def test_outside_the_vault_and_its_settings_are_refused(vault):
    root, ns = vault
    with pytest.raises(PermissionError):
        ns["Vault"].read("../../etc")
    with pytest.raises(PermissionError):
        ns["Vault"].write("/.obsidian/app.json", "{}")


def test_a_second_run_moves_here_to_the_next_note(vault):
    root, ns = vault
    exec(vault_boot(str(root), "top.md"), ns)
    assert ns["Vault"].here == root.resolve()


def test_after_the_cell_the_kernel_leaves_the_notes_folder(vault):
    # A working directory cannot be removed on Windows: parked in the note's
    # folder, the kernel would block deleting or renaming it.
    root, ns = vault
    exec(VAULT_DONE, ns)
    assert os.getcwd() == str(root.resolve())
