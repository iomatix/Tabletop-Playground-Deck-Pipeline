"""
PDF Card Deck & Document Extraction Engine.

Renders vector-based card pages and documents from PDF files into paired
front/back PNG images according to declarative grid profiles and duplex rules.
Emits a contract file (deck_meta.json) for downstream packaging tools.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional

import pymupdf

POINTS_PER_INCH: Final[float] = 72.0


@dataclass(frozen=True)
class GridConfig:
    cols: int
    rows: int
    card_width_pt: float
    card_height_pt: float
    origin_x_pt: float
    origin_y_pt: float
    gutter_x_pt: float = 0.0
    gutter_y_pt: float = 0.0


@dataclass(frozen=True)
class DeckProfile:
    name: str
    grid: GridConfig
    duplex_flip: str = "horizontal"


class PdfDeckExtractor:
    """Extracts duplex card grids and single-sheet documents strictly from allow-listed PDFs."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config.json"
        self.cache_path = base_dir / ".build_cache.json"

        self.cfg = self._load_json(self.config_path, fail_fast=True)
        self.dpi: int = self.cfg.get("dpi", 200)

        if self.dpi <= 0:
            self._fail_fast(f"Invalid DPI value: {self.dpi}. Must be > 0.")

        scale_factor = self.dpi / POINTS_PER_INCH
        self.matrix = pymupdf.Matrix(scale_factor, scale_factor)

        dirs_cfg = self.cfg.get("dirs", {})
        self.input_root = self.base_dir / dirs_cfg.get("input", "_INPUT")
        self.output_root = self.base_dir / dirs_cfg.get("output", "_OUTPUT")

        if not self.input_root.exists():
            self._fail_fast(f"Input directory does not exist: {self.input_root}")

        self.cache = self._load_cache()

    @staticmethod
    def _fail_fast(message: str) -> None:
        print(f"[FAIL-FAST] {message}", file=sys.stderr)
        sys.exit(1)

    def _load_json(self, path: Path, fail_fast: bool = False) -> dict[str, Any]:
        if not path.exists():
            if fail_fast:
                self._fail_fast(f"Required configuration file missing: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:
            self._fail_fast(f"Failed to parse JSON file {path}: {exc}")
            return {}

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}

    def _save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as file:
                json.dump(self.cache, file, indent=2)
        except Exception as exc:
            print(f"[WARN] Failed to write build cache: {exc}", file=sys.stderr)

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            while chunk := file.read(65536):
                digest.update(chunk)
        return digest.hexdigest()

    def resolve_profile_and_rule(self, pdf_path: Path) -> tuple[Optional[DeckProfile], Optional[str]]:
        """Strictly matches PDF against declared rules in config.json or a local deck.json."""
        matched_rule_profile: Optional[str] = None
        strip_suffix: Optional[str] = None

        for rule in self.cfg.get("rules", []):
            pattern = rule.get("pattern", "")
            if pdf_path.match(pattern) or Path(pdf_path.name).match(pattern):
                matched_rule_profile = rule.get("profile")
                strip_suffix = rule.get("strip_suffix")
                break

        local_config_path = pdf_path.parent / "deck.json"

        # Strict Allow-List: Ignore files without an explicit rule or explicit local config
        if not matched_rule_profile and not local_config_path.exists():
            return None, None

        profile_name = matched_rule_profile or self.cfg.get("default_profile", "story_engine_standard")
        base_profile = self.cfg.get("profiles", {}).get(profile_name)

        if not base_profile:
            self._fail_fast(f"Profile '{profile_name}' is referenced in rules but not defined in profiles.")

        grid_raw = dict(base_profile["grid"])
        duplex_flip = base_profile.get("duplex_flip", "horizontal")

        if local_config_path.exists():
            local_overrides = self._load_json(local_config_path)
            if "duplex_flip" in local_overrides:
                duplex_flip = local_overrides["duplex_flip"]
            if "grid_overrides" in local_overrides:
                grid_raw.update(local_overrides["grid_overrides"])

        grid = GridConfig(
            cols=int(grid_raw["cols"]),
            rows=int(grid_raw["rows"]),
            card_width_pt=float(grid_raw["card_width_pt"]),
            card_height_pt=float(grid_raw["card_height_pt"]),
            origin_x_pt=float(grid_raw["origin_x_pt"]),
            origin_y_pt=float(grid_raw["origin_y_pt"]),
            gutter_x_pt=float(grid_raw.get("gutter_x_pt", 0.0)),
            gutter_y_pt=float(grid_raw.get("gutter_y_pt", 0.0)),
        )

        return DeckProfile(name=profile_name, grid=grid, duplex_flip=duplex_flip), strip_suffix

    def _determine_output_directory(self, pdf_path: Path, strip_suffix: Optional[str]) -> Path:
        target_relative_dir = pdf_path.parent.relative_to(self.input_root)
        clean_stem = pdf_path.stem

        if strip_suffix and clean_stem.endswith(strip_suffix):
            clean_stem = clean_stem[: -len(strip_suffix)].rstrip(" _-")

        output_dir = self.output_root / target_relative_dir / clean_stem
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def process_pdf(self, pdf_path: Path) -> None:
        profile, strip_suffix = self.resolve_profile_and_rule(pdf_path)
        if not profile:
            print(f"[IGNORE] Skipping unlisted file: {pdf_path.name}")
            return

        cache_key = str(pdf_path.relative_to(self.input_root))
        current_hash = self._compute_sha256(pdf_path)
        cache_state = json.dumps(
            {
                "hash": current_hash,
                "profile": profile.name,
                "duplex_flip": profile.duplex_flip,
                "dpi": self.dpi,
            },
            sort_keys=True,
        )

        deck_output_dir = self._determine_output_directory(pdf_path, strip_suffix)

        if (
            self.cache.get(cache_key) == cache_state
            and any(deck_output_dir.glob("card_*_front.png"))
            and (deck_output_dir / "deck_meta.json").exists()
        ):
            print(f"[SKIP] {pdf_path.name} (cached)")
            return

        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)

        # Standalone single-page self-healing
        if total_pages == 1:
            full_page_cfg = self.cfg.get("profiles", {}).get("full_page_duplex")
            if full_page_cfg:
                grid_raw = full_page_cfg["grid"]
                profile = DeckProfile(
                    name="full_page_duplex",
                    grid=GridConfig(
                        cols=1,
                        rows=1,
                        card_width_pt=float(grid_raw["card_width_pt"]),
                        card_height_pt=float(grid_raw["card_height_pt"]),
                        origin_x_pt=float(grid_raw["origin_x_pt"]),
                        origin_y_pt=float(grid_raw["origin_y_pt"]),
                        gutter_x_pt=0.0,
                        gutter_y_pt=0.0,
                    ),
                    duplex_flip="none",
                )

        is_document = profile.grid.cols == 1 and profile.grid.rows == 1

        # Enforce duplex parity on multi-card decks
        if not is_document and total_pages % 2 != 0:
            doc.close()
            self._fail_fast(
                f"Odd page count ({total_pages}) detected in double-sided deck: {pdf_path.name}. "
                "Verify duplex binding or assign a single-page document profile."
            )

        print(
            f"\n[PROCESS] Extracting: {pdf_path.name} -> Profile: {profile.name} (Type: {'Document' if is_document else 'Card Deck'})"
        )

        grid = profile.grid
        card_counter = 1
        sheet_pairs = (total_pages + 1) // 2

        # Dynamically calculate zero-padding width (minimum 3 digits, expands for >= 1000 items)
        expected_total_cards = sheet_pairs * (1 if is_document else grid.cols * grid.rows)
        pad_width = max(3, len(str(expected_total_cards)))

        for pair_idx in range(sheet_pairs):
            front_idx = pair_idx * 2
            back_idx = front_idx + 1

            front_page = doc[front_idx]
            back_page = doc[back_idx] if back_idx < total_pages else None

            for row in range(grid.rows):
                for col in range(grid.cols):
                    if is_document:
                        front_rect = front_page.rect
                        back_rect = back_page.rect if back_page else front_page.rect
                    else:
                        fx0 = grid.origin_x_pt + col * (grid.card_width_pt + grid.gutter_x_pt)
                        fy0 = grid.origin_y_pt + row * (grid.card_height_pt + grid.gutter_y_pt)
                        front_rect = pymupdf.Rect(fx0, fy0, fx0 + grid.card_width_pt, fy0 + grid.card_height_pt)

                        if profile.duplex_flip == "horizontal":
                            back_col = grid.cols - 1 - col
                            back_row = row
                        elif profile.duplex_flip == "vertical":
                            back_col = col
                            back_row = grid.rows - 1 - row
                        else:
                            back_col = col
                            back_row = row

                        bx0 = grid.origin_x_pt + back_col * (grid.card_width_pt + grid.gutter_x_pt)
                        by0 = grid.origin_y_pt + back_row * (grid.card_height_pt + grid.gutter_y_pt)
                        back_rect = pymupdf.Rect(bx0, by0, bx0 + grid.card_width_pt, by0 + grid.card_height_pt)

                    front_pix = front_page.get_pixmap(matrix=self.matrix, clip=front_rect, alpha=False)
                    front_pix.save(deck_output_dir / f"card_{card_counter:0{pad_width}d}_front.png")

                    if back_page:
                        back_pix = back_page.get_pixmap(matrix=self.matrix, clip=back_rect, alpha=False)
                        back_pix.save(deck_output_dir / f"card_{card_counter:0{pad_width}d}_back.png")
                    else:
                        target_w = front_rect.width
                        target_h = front_rect.height
                        blank_pix = pymupdf.Pixmap(
                            pymupdf.csRGB,
                            pymupdf.IRect(
                                0,
                                0,
                                int(target_w * (self.dpi / POINTS_PER_INCH)),
                                int(target_h * (self.dpi / POINTS_PER_INCH)),
                            ),
                        )
                        blank_pix.clear_with(255)
                        blank_pix.save(deck_output_dir / f"card_{card_counter:0{pad_width}d}_back.png")

                    card_counter += 1

        total_extracted = card_counter - 1
        doc.close()

        # Emit contract metadata file for ttpg_packager.py
        meta_contract = {
            "source_pdf": pdf_path.name,
            "item_type": "document" if is_document else "card_deck",
            "profile": profile.name,
            "total_items": total_extracted,
            "duplex_flip": profile.duplex_flip,
            "grid": {
                "cols": grid.cols,
                "rows": grid.rows,
                "card_width_pt": grid.card_width_pt,
                "card_height_pt": grid.card_height_pt,
            },
        }
        with open(deck_output_dir / "deck_meta.json", "w", encoding="utf-8") as meta_file:
            json.dump(meta_contract, meta_file, indent=2)

        self.cache[cache_key] = cache_state
        print(f"  [+] Saved {total_extracted} items and deck_meta.json into: {deck_output_dir}")

    def run(self) -> None:
        pdf_files = sorted(list(self.input_root.rglob("*.pdf")))
        if not pdf_files:
            print(f"[INFO] No PDF files found in: {self.input_root}")
            return

        print(f"[*] Starting extraction from {self.input_root}. Discovered {len(pdf_files)} PDF candidate(s).")
        self.output_root.mkdir(parents=True, exist_ok=True)

        for pdf in pdf_files:
            self.process_pdf(pdf)

        self._save_cache()
        print("\n[OK] Card extraction completed successfully.")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    extractor = PdfDeckExtractor(base_dir)
    extractor.run()


if __name__ == "__main__":
    main()
