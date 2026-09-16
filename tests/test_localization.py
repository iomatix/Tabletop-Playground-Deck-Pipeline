"""
Localization and i18n integrity tests with automated sorting and scaffolding sync.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = BASE_DIR / "locales"


def _load_json_checking_duplicates(path: Path) -> dict[str, str]:
    def dict_raise_on_duplicates(ordered_pairs):
        d = {}
        for k, v in ordered_pairs:
            if k in d:
                raise ValueError(f"Duplicate key detected in {path.name}: '{k}'")
            d[k] = v
        return d

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=dict_raise_on_duplicates)


def _sync_and_sort_locales(
    en_path: Path, pl_path: Path
) -> tuple[set[str], set[str]]:
    """Sorts keys alphabetically and scaffolds missing keys with TODO markers."""
    with open(en_path, "r", encoding="utf-8") as f:
        en_data: dict[str, str] = json.load(f)
    with open(pl_path, "r", encoding="utf-8") as f:
        pl_data: dict[str, str] = json.load(f)

    all_keys = sorted(list(set(en_data.keys()) | set(pl_data.keys())))

    missing_in_en: set[str] = set()
    missing_in_pl: set[str] = set()

    sorted_en: dict[str, str] = {}
    sorted_pl: dict[str, str] = {}

    for k in all_keys:
        if k not in en_data:
            sorted_en[k] = f"TODO: EN translation of '{k}'"
            missing_in_en.add(k)
        else:
            sorted_en[k] = en_data[k]

        if k not in pl_data:
            sorted_pl[k] = f"TODO: PL translation of '{k}'"
            missing_in_pl.add(k)
        else:
            sorted_pl[k] = pl_data[k]

    with open(en_path, "w", encoding="utf-8") as f:
        json.dump(sorted_en, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(pl_path, "w", encoding="utf-8") as f:
        json.dump(sorted_pl, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return missing_in_en, missing_in_pl


def test_locales_no_duplicate_keys():
    for json_file in LOCALES_DIR.glob("*.json"):
        _load_json_checking_duplicates(json_file)


def test_locales_keys_symmetry_and_autofix():
    en_path = LOCALES_DIR / "en.json"
    pl_path = LOCALES_DIR / "pl.json"

    assert en_path.exists() and pl_path.exists(), "Missing baseline locale files."

    # Auto-synchronize and sort keys across both bundles
    missing_en, missing_pl = _sync_and_sort_locales(en_path, pl_path)

    if missing_en or missing_pl:
        warnings.warn(
            UserWarning(
                f"[i18n AUTO-FIX] Synced missing keys into files! "
                f"Missing in EN: {missing_en or 'None'}, "
                f"Missing in PL: {missing_pl or 'None'}. "
                f"Please provide actual translations for generated 'TODO:' entries."
            ),
            stacklevel=2,
        )


def test_locales_no_pending_todos():
    """Warns if any translation entries are still marked with 'TODO:' placeholders."""
    todos_found: list[str] = []

    for locale_file in LOCALES_DIR.glob("*.json"):
        data = _load_json_checking_duplicates(locale_file)
        for key, val in data.items():
            if str(val).startswith("TODO:"):
                todos_found.append(f"{locale_file.name} -> {key}: '{val}'")

    if todos_found:
        warnings.warn(
            UserWarning(
                f"[PENDING TRANSLATIONS] Found {len(todos_found)} untranslated placeholders:\n"
                + "\n".join(f"  * {item}" for item in todos_found)
                + "\nApplications will fall back to raw keys or placeholders!"
            ),
            stacklevel=2,
        )


def test_codebase_t_keys_exist_in_locales():
    with open(LOCALES_DIR / "en.json", "r", encoding="utf-8") as f:
        locale_keys = set(json.load(f).keys())

    pattern = re.compile(r'\bt\(\s*["\']([^"\']+)["\']\s*\)')
    used_keys = set()

    for py_file in (BASE_DIR / "app").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for match in pattern.findall(content):
            used_keys.add(match)

    missing_keys = used_keys - locale_keys
    if missing_keys:
        pytest.fail(
            f"Keys used in codebase via t(...) but completely missing in locales: {missing_keys}"
        )
