"""
Diagnostic PDF Card Inspector (v1.1.0).

Renders and extracts a test card pair (front and back) using declarative rules,
local deck.json overrides, or dynamic 1D vector auto-detection (PdfGridAnalyzer).
"""

from __future__ import annotations

import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pymupdf

from app.pdf_analyzer import PdfGridAnalyzer

POINTS_PER_INCH: Final[float] = 72.0
CENTIMETERS_PER_INCH: Final[float] = 2.54


@dataclass(frozen=True)
class GridSpec:
    cols: int
    rows: int
    card_width_pt: float
    card_height_pt: float
    origin_x_pt: float
    origin_y_pt: float
    gutter_x_pt: float = 0.0
    gutter_y_pt: float = 0.0


class DeckInspector:
    """Isolates sample card bounding boxes to validate grid math and margins."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config.json"

        if not self.config_path.exists():
            self._fail_fast(f"Configuration file does not exist: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                self.cfg: dict[str, Any] = json.load(file)
        except Exception as exc:
            self._fail_fast(f"Failed to read {self.config_path}: {exc}")

        self.dpi: int = self.cfg.get("dpi", 200)
        if self.dpi <= 0:
            self._fail_fast(f"Invalid DPI value ({self.dpi}). Must be > 0.")

        self.scale = self.dpi / POINTS_PER_INCH
        self.matrix = pymupdf.Matrix(self.scale, self.scale)

        dirs_cfg = self.cfg.get("dirs", {})
        self.input_dir = self.base_dir / dirs_cfg.get("input", "_INPUT")
        self.diag_dir = self.base_dir / dirs_cfg.get("diagnostics", "_DIAGNOSTICS")

        if not self.input_dir.exists():
            self._fail_fast(f"Input directory does not exist: {self.input_dir}")

        self.diag_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fail_fast(message: str) -> None:
        print(f"[FAIL-FAST] {message}", file=sys.stderr)
        sys.exit(1)

    def _resolve_sample_pdf(self) -> Path:
        if len(sys.argv) > 1:
            explicit_path = Path(sys.argv[1])
            if explicit_path.exists():
                return explicit_path
            target_in_input = self.input_dir / sys.argv[1]
            if target_in_input.exists():
                return target_in_input
            self._fail_fast(f"Specified PDF target does not exist: {sys.argv[1]}")

        candidates = sorted(list(self.input_dir.rglob("*.pdf")))
        if not candidates:
            self._fail_fast(f"No valid PDF candidates found in: {self.input_dir}")

        return candidates[0]

    def _resolve_profile(self, pdf_path: Path) -> tuple[GridSpec, str, str]:
        """
        Resolves grid parameters with the following hierarchy:
        1. Local deck.json overrides (if present)
        2. Pattern match from config.json rules
        3. Dynamic 1D vector auto-detection via PdfGridAnalyzer
        """
        local_config_path = pdf_path.parent / "deck.json"
        profile_key = None

        for rule in self.cfg.get("rules", []):
            pattern = rule.get("pattern", "")
            if pattern and fnmatch.fnmatch(pdf_path.name, pattern):
                profile_key = rule.get("profile")
                break

        origin_source = "matched rule"
        grid_raw: dict[str, Any] = {}
        duplex_flip = "horizontal"

        if profile_key and profile_key in self.cfg.get("profiles", {}):
            profile_data = self.cfg["profiles"][profile_key]
            grid_raw = dict(profile_data["grid"])
            duplex_flip = profile_data.get("duplex_flip", "horizontal")
        else:
            # Dynamic fallback: Use PdfGridAnalyzer 1D vector decomposition
            print(f"[INFO] No explicit rule matched for '{pdf_path.name}'. Running PdfGridAnalyzer...")
            detection = PdfGridAnalyzer.detect_grid(pdf_path)
            grid_raw = {
                "cols": detection["cols"],
                "rows": detection["rows"],
                "card_width_pt": detection["card_width_pt"],
                "card_height_pt": detection["card_height_pt"],
                "origin_x_pt": detection["origin_x_pt"],
                "origin_y_pt": detection["origin_y_pt"],
                "gutter_x_pt": detection["gutter_x_pt"],
                "gutter_y_pt": detection["gutter_y_pt"],
            }
            duplex_flip = detection.get("duplex_flip", "none")
            origin_source = f"auto-detected ({detection.get('detected_type', 'Dynamic')})"

        if local_config_path.exists():
            try:
                with open(local_config_path, "r", encoding="utf-8") as file:
                    loc = json.load(file)
                if "duplex_flip" in loc:
                    duplex_flip = loc["duplex_flip"]
                if "grid_overrides" in loc:
                    grid_raw.update(loc["grid_overrides"])
                origin_source += " + deck.json overrides"
            except Exception as exc:
                print(f"[WARN] Failed to read overrides from {local_config_path}: {exc}", file=sys.stderr)

        grid = GridSpec(
            cols=int(grid_raw["cols"]),
            rows=int(grid_raw["rows"]),
            card_width_pt=float(grid_raw["card_width_pt"]),
            card_height_pt=float(grid_raw["card_height_pt"]),
            origin_x_pt=float(grid_raw["origin_x_pt"]),
            origin_y_pt=float(grid_raw["origin_y_pt"]),
            gutter_x_pt=float(grid_raw.get("gutter_x_pt", 0.0)),
            gutter_y_pt=float(grid_raw.get("gutter_y_pt", 0.0)),
        )

        return grid, duplex_flip, origin_source

    def run(self) -> None:
        sample_pdf = self._resolve_sample_pdf()

        try:
            with pymupdf.open(sample_pdf) as doc:
                if doc.is_encrypted:
                    self._fail_fast(f"PDF document is encrypted: {sample_pdf.name}")
                if len(doc) == 0:
                    self._fail_fast(f"PDF document contains no pages: {sample_pdf.name}")

                grid, duplex_flip, source = self._resolve_profile(sample_pdf)

                # Inspect top-left cell (col=0, row=0)
                fx0 = grid.origin_x_pt
                fy0 = grid.origin_y_pt
                front_rect = pymupdf.Rect(fx0, fy0, fx0 + grid.card_width_pt, fy0 + grid.card_height_pt)

                out_front = self.diag_dir / "precise_card_000_front.png"
                pix_front = doc[0].get_pixmap(matrix=self.matrix, clip=front_rect, alpha=False)
                pix_front.save(out_front)

                has_back = len(doc) > 1 and duplex_flip != "none"
                out_back = self.diag_dir / "precise_card_000_back.png"

                if has_back:
                    target_col, target_row = 0, 0
                    if duplex_flip == "horizontal":
                        back_col = grid.cols - 1 - target_col
                        back_row = target_row
                    elif duplex_flip == "vertical":
                        back_col = target_col
                        back_row = grid.rows - 1 - target_row
                    else:
                        back_col, back_row = target_col, target_row

                    bx0 = grid.origin_x_pt + back_col * (grid.card_width_pt + grid.gutter_x_pt)
                    by0 = grid.origin_y_pt + back_row * (grid.card_height_pt + grid.gutter_y_pt)
                    back_rect = pymupdf.Rect(bx0, by0, bx0 + grid.card_width_pt, by0 + grid.card_height_pt)

                    pix_back = doc[1].get_pixmap(matrix=self.matrix, clip=back_rect, alpha=False)
                    pix_back.save(out_back)

                width_cm = (pix_front.width / self.dpi) * CENTIMETERS_PER_INCH
                height_cm = (pix_front.height / self.dpi) * CENTIMETERS_PER_INCH

                print(f"[OK] Inspected Document : {sample_pdf.name}")
                print(f"[OK] Resolution Engine  : {source}")
                print(f"[OK] Grid Geometry      : {grid.cols}x{grid.rows} (Card: {grid.card_width_pt}x{grid.card_height_pt} pt)")
                print(f"[OK] Duplex Mode        : {duplex_flip}")
                print(f"[OK] Front Sample       : {out_front.name} ({pix_front.width}x{pix_front.height} px)")
                if has_back:
                    print(f"[OK] Back Sample        : {out_back.name} ({pix_back.width}x{pix_back.height} px)")
                else:
                    print("[INFO] Back Sample       : Skipped (Single-page document or duplex='none')")
                print(f"[OK] Physical Dimensions: {width_cm:.2f} x {height_cm:.2f} cm (@ {self.dpi} DPI)")

        except Exception as exc:
            self._fail_fast(f"Processing error during inspection: {exc}")


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    inspector = DeckInspector(base_dir)
    inspector.run()


if __name__ == "__main__":
    main()
