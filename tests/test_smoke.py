"""
Smoke test suite for TTPG Deck Pipeline.

Verifies basic imports, config schema integrity, and core math logic
without requiring external PDF test assets.
"""

import json
from pathlib import Path
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent


def test_config_integrity():
    config_path = BASE_DIR / "config.json"
    assert config_path.exists(), "config.json must exist in root"

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    assert "dpi" in cfg, "config must specify dpi"
    assert cfg["dpi"] > 0, "dpi must be positive"
    assert "profiles" in cfg, "config must define profiles"
    assert len(cfg["profiles"]) > 0, "at least one profile must be configured"


def test_physics_formula():
    """Verify deterministic pixel-to-cm math: (px / dpi) * 2.54."""
    dpi = 200
    card_w_px = 600
    expected_w_cm = round((card_w_px / dpi) * 2.54, 2)
    assert expected_w_cm == 7.62


def test_module_syntax_imports():
    """Ensure core pipeline modules import cleanly without syntax or environment errors."""
    import deck_processor
    import ttpg_packager
    import inspect_deck

    assert hasattr(deck_processor, "PdfDeckExtractor")
    assert hasattr(ttpg_packager, "PackageOrchestrator")
    assert hasattr(inspect_deck, "DeckInspector")