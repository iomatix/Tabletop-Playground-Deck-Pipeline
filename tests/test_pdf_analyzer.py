"""
Unit tests for 1D differential analyzer and PDF inspection safety.
"""

from pathlib import Path
from app.pdf_analyzer import _cluster_1d, _decompose_axis, PdfGridAnalyzer


def test_cluster_1d_with_jitter():
    raw_coords = [9.8, 10.1, 10.0, 49.9, 50.2, 50.0]
    clusters = _cluster_1d(raw_coords, tolerance=2.0)
    assert len(clusters) == 2
    assert clusters[0] == 10.0
    assert clusters[1] == 50.0


def test_decompose_axis_standard_cards():
    coords = [36.0, 216.0, 396.0, 576.0]
    page_dim = 612.0
    count, card_size, origin, gutter = _decompose_axis(coords, page_dim)
    assert count == 3
    assert card_size == 180.0
    assert origin == 36.0
    assert gutter == 0.0


def test_decompose_axis_with_gutters():
    coords = [80.95, 296.95, 314.95, 530.95]
    page_dim = 612.0
    count, card_size, origin, gutter = _decompose_axis(coords, page_dim)
    assert count == 2
    assert card_size == 216.0
    assert origin == 80.95
    assert gutter == 18.0


def test_detect_grid_non_existent_file():
    res = PdfGridAnalyzer.detect_grid(Path("non_existent_file.pdf"))
    assert res["is_valid"] is False
    assert res["cols"] == 1
    assert res["rows"] == 1