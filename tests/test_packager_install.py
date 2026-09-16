"""
Unit and integration tests for TTPG package installation logic.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def simulate_install(source_pkg: Path, target_dir: Path, pkg_name: str) -> tuple[bool, str]:
    if not source_pkg.exists():
        return False, f"Source path does not exist: {source_pkg}"

    target_dest = target_dir / pkg_name
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copytree(source_pkg, target_dest, dirs_exist_ok=True)
    except Exception as exc:
        return False, f"shutil.copytree error: {exc}"

    manifest_file = target_dest / "Manifest.json"
    if not manifest_file.exists():
        return False, f"Manifest.json missing at destination: {target_dest}"

    return True, f"Successfully installed to {target_dest}"


def test_package_install_mock(tmp_path: Path):
    # Create mock package structure
    src = tmp_path / "_PACKAGE" / "MockDeck"
    (src / "Templates").mkdir(parents=True)
    (src / "Textures").mkdir(parents=True)
    (src / "Manifest.json").write_text(json.dumps({"Name": "MockDeck"}), encoding="utf-8")

    ttpg_target_dir = tmp_path / "TTPG_Packages"

    ok, msg = simulate_install(src, ttpg_target_dir, "MockDeck")
    assert ok is True
    assert (ttpg_target_dir / "MockDeck" / "Manifest.json").exists()
    assert (ttpg_target_dir / "MockDeck" / "Templates").is_dir()
    assert (ttpg_target_dir / "MockDeck" / "Textures").is_dir()
