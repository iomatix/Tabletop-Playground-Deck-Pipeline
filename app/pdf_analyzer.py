"""
PDF Vector Inspection, 1D Differential Grid Decomposition,
and Click-Through SVG Overlay Generator.
"""

from __future__ import annotations

import base64
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Optional

import pymupdf

from app.state import PREVIEW_SCALE, t


def _cluster_1d(values: list[float], tolerance: float = 2.0) -> list[float]:
    """Clusters 1D coordinates within a tolerance window and returns cluster medians."""
    if not values:
        return []
    sorted_vals = sorted(values)
    clusters: list[list[float]] = [[sorted_vals[0]]]

    for val in sorted_vals[1:]:
        if val - clusters[-1][-1] <= tolerance:
            clusters[-1].append(val)
        else:
            clusters.append([val])

    return [round(float(median(c)), 2) for c in clusters]


def _decompose_axis(
    coords: list[float], page_dimension: float
) -> tuple[int, float, float, float]:
    """
    Analyzes 1D cut coordinates using first-order differences.
    Selects dominant cluster frequency to determine card size.
    Returns: (count, card_dimension_pt, origin_pt, gutter_pt)
    """
    if len(coords) < 2:
        return 1, page_dimension, 0.0, 0.0

    deltas = [round(coords[i + 1] - coords[i], 2) for i in range(len(coords) - 1)]
    valid_deltas = [d for d in deltas if d >= 1.0]

    if not valid_deltas:
        return 1, page_dimension, 0.0, 0.0

    # Differentiate between card spans (>= 60 pt) and gutters (< 50 pt)
    card_deltas = [d for d in valid_deltas if d >= 60.0]
    gutter_deltas = [d for d in valid_deltas if 0.5 <= d < 50.0]

    if not card_deltas:
        return 1, page_dimension, 0.0, 0.0

    # Cluster deltas and select the dominant (most frequent) bucket
    raw_clusters = _cluster_1d(card_deltas, tolerance=3.0)
    
    # Map raw deltas to closest cluster centroid to establish cluster sizes
    def find_nearest_centroid(val: float) -> float:
        return min(raw_clusters, key=lambda c: abs(c - val))

    cluster_counts = Counter(find_nearest_centroid(d) for d in card_deltas)
    card_size, dominant_count = cluster_counts.most_common(1)[0]

    gutter = 0.0
    if gutter_deltas:
        gutter_clusters = _cluster_1d(gutter_deltas, tolerance=2.0)
        gutter_counter = Counter(min(gutter_clusters, key=lambda g: abs(g - d)) for d in gutter_deltas)
        gutter = gutter_counter.most_common(1)[0][0]

    origin = coords[0]
    return max(1, dominant_count), card_size, origin, gutter


class PdfGridAnalyzer:
    """Extracts vector cut lines, dimensions, and raster previews from PDF files with Fail-Fast resilience."""

    @staticmethod
    def detect_grid(pdf_path: Path) -> dict[str, Any]:
        default_fallback = {
            "cols": 1,
            "rows": 1,
            "card_width_pt": 595.0,
            "card_height_pt": 842.0,
            "origin_x_pt": 0.0,
            "origin_y_pt": 0.0,
            "gutter_x_pt": 0.0,
            "gutter_y_pt": 0.0,
            "duplex_flip": "none",
            "detected_type": t("type_doc_fallback"),
            "is_valid": False,
        }

        if not pdf_path.exists() or not pdf_path.is_file():
            return default_fallback

        try:
            with pymupdf.open(pdf_path) as doc:
                if doc.is_encrypted or len(doc) == 0:
                    return default_fallback

                total_pages = len(doc)
                page = doc[0]
                page_w = round(page.rect.width, 2)
                page_h = round(page.rect.height, 2)

                default_fallback["card_width_pt"] = page_w
                default_fallback["card_height_pt"] = page_h

                # Early check for document/manual characteristics
                text_content = page.get_text().strip()
                has_heavy_text = len(text_content.splitlines()) > 20
                is_named_doc = any(
                    marker in pdf_path.name.lower()
                    for marker in ("guidebook", "instruction", "manual", "rulebook", "rules")
                )

                drawings = page.get_drawings()

                if (total_pages <= 2 and has_heavy_text) or is_named_doc or len(drawings) < 4:
                    return {
                        **default_fallback,
                        "card_width_pt": page_w,
                        "card_height_pt": page_h,
                        "detected_type": t("type_document_manual"),
                        "is_valid": True,
                    }

                # Extract Vector Cut Candidates
                xs: list[float] = []
                ys: list[float] = []

                for d in drawings:
                    rect = d.get("rect")
                    if rect:
                        if rect.width <= 3.0 and rect.height >= 4.0:
                            if 5.0 < rect.x0 < (page_w - 5.0):
                                xs.append(rect.x0)
                        elif rect.height <= 3.0 and rect.width >= 4.0:
                            if 5.0 < rect.y0 < (page_h - 5.0):
                                ys.append(rect.y0)

                    for item in d.get("items", []):
                        if item[0] == "l":
                            p1, p2 = item[1], item[2]
                            if abs(p1.x - p2.x) <= 1.0 and 5.0 < p1.x < (page_w - 5.0):
                                xs.append(p1.x)
                            elif abs(p1.y - p2.y) <= 1.0 and 5.0 < p1.y < (page_h - 5.0):
                                ys.append(p1.y)

                clustered_xs = _cluster_1d(xs, tolerance=2.0)
                clustered_ys = _cluster_1d(ys, tolerance=2.0)

                cols, w_pt, ox_pt, gx_pt = _decompose_axis(clustered_xs, page_w)
                rows, h_pt, oy_pt, gy_pt = _decompose_axis(clustered_ys, page_h)

                is_valid_grid = (cols > 1 or rows > 1) and w_pt >= 60.0 and h_pt >= 60.0
                if not is_valid_grid:
                    return {
                        **default_fallback,
                        "card_width_pt": page_w,
                        "card_height_pt": page_h,
                        "detected_type": t("type_full_sheet"),
                        "is_valid": True,
                    }

                ratio = min(w_pt, h_pt) / max(w_pt, h_pt)
                if 0.95 <= ratio <= 1.05:
                    card_type = t("type_square_cards")
                elif 0.66 <= ratio <= 0.76:
                    card_type = t("type_standard_poker")
                elif 0.54 <= ratio <= 0.65:
                    card_type = t("type_mini_tarot")
                else:
                    card_type = t("type_custom_grid")

                return {
                    "cols": cols,
                    "rows": rows,
                    "card_width_pt": w_pt,
                    "card_height_pt": h_pt,
                    "origin_x_pt": ox_pt,
                    "origin_y_pt": oy_pt,
                    "gutter_x_pt": gx_pt,
                    "gutter_y_pt": gy_pt,
                    "duplex_flip": "horizontal" if total_pages > 1 else "none",
                    "detected_type": card_type,
                    "is_valid": True,
                }
        except Exception:
            return default_fallback

    @staticmethod
    def render_page_base64(pdf_path: Path, page_num: int = 0) -> tuple[str, float, float]:
        if not pdf_path.exists():
            return "", 0.0, 0.0

        try:
            with pymupdf.open(pdf_path) as doc:
                if doc.is_encrypted or len(doc) <= page_num:
                    return "", 0.0, 0.0
                page = doc[page_num]
                matrix = pymupdf.Matrix(PREVIEW_SCALE, PREVIEW_SCALE)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                img_bytes = pixmap.tobytes("png")
                b64_str = base64.b64encode(img_bytes).decode("utf-8")
                return f"data:image/png;base64,{b64_str}", float(pixmap.width), float(pixmap.height)
        except Exception:
            return "", 0.0, 0.0


def generate_overlay_svg(
    cols: int,
    rows: int,
    ox: float,
    oy: float,
    w: float,
    h: float,
    gx: float,
    gy: float,
    img_w: float = 0.0,
    img_h: float = 0.0,
    calibrating_origin: bool = False,
    first_click_point: tuple[float, float] | None = None,
) -> str:
    """Generates an SVG overlay with click-through styling and localized markers."""
    svg_elements: list[str] = []
    card_index = 1

    for r in range(rows):
        for c in range(cols):
            x = (ox + c * (w + gx)) * PREVIEW_SCALE
            y = (oy + r * (h + gy)) * PREVIEW_SCALE
            box_w = w * PREVIEW_SCALE
            box_h = h * PREVIEW_SCALE

            svg_elements.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" '
                f'fill="rgba(33, 150, 243, 0.2)" stroke="#1976d2" stroke-width="2" rx="3" pointer-events="none"/>'
                f'<text x="{x + 6:.1f}" y="{y + 18:.1f}" fill="#ffffff" font-size="13" '
                f'font-family="monospace" font-weight="bold" stroke="#000" stroke-width="0.5" pointer-events="none">#{card_index}</text>'
            )
            card_index += 1

    if first_click_point is not None:
        fx = first_click_point[0] * PREVIEW_SCALE
        fy = first_click_point[1] * PREVIEW_SCALE
        label_point = t("overlay_origin_marker")
        svg_elements.append(
            f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="6" fill="#ff5722" stroke="#fff" stroke-width="2" pointer-events="none"/>'
            f'<text x="{fx + 10:.1f}" y="{fy + 4:.1f}" fill="#ff5722" font-size="12" '
            f'font-weight="bold" stroke="#fff" stroke-width="0.5" pointer-events="none">{label_point}</text>'
        )

    body = "".join(svg_elements)
    if img_w > 0 and img_h > 0:
        return f'<svg viewBox="0 0 {img_w:.1f} {img_h:.1f}" width="100%" height="100%" style="pointer-events: none;">{body}</svg>'
    return body