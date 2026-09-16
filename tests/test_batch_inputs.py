"""
Batch integration tests for local PDF input assets.
"""

from pathlib import Path
import pytest
from app.pdf_analyzer import PdfGridAnalyzer

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "_INPUT"

pdf_files = sorted(list(INPUT_DIR.rglob("*.pdf"))) if INPUT_DIR.exists() else []


@pytest.mark.skipif(not pdf_files, reason="No PDFs found in _INPUT directory (CI environment).")
@pytest.mark.parametrize("pdf_path", pdf_files, ids=lambda p: p.name)
def test_all_input_pdfs_parse_successfully(pdf_path: Path):
    result = PdfGridAnalyzer.detect_grid(pdf_path)

    assert result["is_valid"] is True, f"Failed to parse {pdf_path.name}"
    assert result["cols"] >= 1
    assert result["rows"] >= 1
    assert result["card_width_pt"] > 0
    assert result["card_height_pt"] > 0