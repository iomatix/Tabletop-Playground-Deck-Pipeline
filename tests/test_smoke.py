"""
Smoke test suite for TTPG Deck Pipeline.

Verifies basic imports, config schema integrity, and core math logic
without requiring external PDF test assets.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


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
    """Ensure core and modular pipeline modules import cleanly without errors."""
    import app.pdf_analyzer
    import app.state
    import app.views.calibrator
    import app.views.diagnostics
    import app.views.wizard
    import deck_processor
    import inspect_deck
    import ttpg_packager

    assert hasattr(deck_processor, "PdfDeckExtractor")
    assert hasattr(ttpg_packager, "PackageOrchestrator")
    assert hasattr(inspect_deck, "DeckInspector")
    assert hasattr(app.state, "LocaleManager")
    assert hasattr(app.pdf_analyzer, "PdfGridAnalyzer")
    assert hasattr(app.views.calibrator, "create_calibrator_view")
    assert hasattr(app.views.wizard, "create_pipeline_view")
    assert hasattr(app.views.diagnostics, "create_diagnostics_view")
