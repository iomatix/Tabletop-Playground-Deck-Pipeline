"""
Localization and i18n integrity tests.
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = BASE_DIR / "locales"


def _load_json_checking_duplicates(path: Path) -> dict:
    def dict_raise_on_duplicates(ordered_pairs):
        d = {}
        for k, v in ordered_pairs:
            if k in d:
                raise ValueError(f"Duplicate key detected in {path.name}: '{k}'")
            d[k] = v
        return d

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=dict_raise_on_duplicates)


def test_locales_no_duplicate_keys():
    for json_file in LOCALES_DIR.glob("*.json"):
        _load_json_checking_duplicates(json_file)


def test_locales_keys_symmetry():
    en_path = LOCALES_DIR / "en.json"
    pl_path = LOCALES_DIR / "pl.json"

    assert en_path.exists() and pl_path.exists(), "Missing baseline locale files."

    with open(en_path, "r", encoding="utf-8") as f:
        en_keys = set(json.load(f).keys())

    with open(pl_path, "r", encoding="utf-8") as f:
        pl_keys = set(json.load(f).keys())

    missing_in_pl = en_keys - pl_keys
    missing_in_en = pl_keys - en_keys

    assert not missing_in_pl, f"Keys present in EN but missing in PL: {missing_in_pl}"
    assert not missing_in_en, f"Keys present in PL but missing in EN: {missing_in_en}"


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
    assert not missing_keys, f"Keys used in codebase via t(...) but missing in locales: {missing_keys}"