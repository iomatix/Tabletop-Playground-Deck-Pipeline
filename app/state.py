"""
Application State and Configuration Management.

Provides thread-safe loading and persistence for config.json,
localization dictionary management, and shared runtime state.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
CONFIG_PATH: Final[Path] = BASE_DIR / "config.json"
LOCALES_DIR: Final[Path] = BASE_DIR / "locales"
TTPG_PACKAGES_DIR: Final[Path] = Path(os.path.expandvars(r"%LOCALAPPDATA%\TabletopPlayground\Packages"))

PREVIEW_DPI: Final[int] = 100
PREVIEW_SCALE: Final[float] = PREVIEW_DPI / 72.0


@dataclass
class ApplicationState:
    current_lang: str = "en"
    is_busy: bool = False
    execution_logs: list[str] = field(default_factory=list)
    preview_dims: dict[str, float] = field(default_factory=lambda: {"w": 0.0, "h": 0.0})


class ConfigRepository:
    """Handles read and write operations for config.json."""

    @staticmethod
    def load() -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            print(f"[FAIL-FAST] Missing configuration at: {CONFIG_PATH}", file=sys.stderr)
            return {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:
            print(f"[FAIL-FAST] Failed to parse config.json: {exc}", file=sys.stderr)
            return {}

    @staticmethod
    def save(data: dict[str, Any]) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
        except Exception as exc:
            print(f"[ERROR] Failed to save config: {exc}", file=sys.stderr)


class LocaleManager:
    """Manages multi-language dictionaries with English fallback."""

    def __init__(self, locales_dir: Path) -> None:
        self.locales: dict[str, dict[str, str]] = {}
        if locales_dir.exists():
            for locale_file in locales_dir.glob("*.json"):
                try:
                    with open(locale_file, "r", encoding="utf-8") as file:
                        self.locales[locale_file.stem] = json.load(file)
                except Exception as exc:
                    print(f"[WARN] Failed to load locale {locale_file.name}: {exc}", file=sys.stderr)

    def translate(self, key: str, lang: str) -> str:
        return self.locales.get(lang, {}).get(key, self.locales.get("en", {}).get(key, key))


# Shared instances
state = ApplicationState()
config_data = ConfigRepository.load()
locale_mgr = LocaleManager(LOCALES_DIR)


def t(key: str) -> str:
    """Shortcut function for localization lookups."""
    return locale_mgr.translate(key, state.current_lang)


def open_system_folder(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    current_os = platform.system()
    try:
        if current_os == "Windows":
            os.startfile(str(path))
        elif current_os == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:
        print(f"[ERROR] Could not open folder {path}: {exc}", file=sys.stderr)


def get_input_dir() -> Path:
    return BASE_DIR / config_data.get("dirs", {}).get("input", "_INPUT")


def get_pdf_candidates() -> list[Path]:
    in_dir = get_input_dir()
    if not in_dir.exists():
        return []
    return sorted(list(in_dir.rglob("*.pdf")))
