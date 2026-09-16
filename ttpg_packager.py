"""
Tabletop Playground (TTPG) Package & Deck Compiler.

Handles multi-sheet texture atlas stitching, dynamic physics calculation
from DPI and pixel dimensions, hierarchical configuration resolution, and
generation of unified TTPG Card templates.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional

from PIL import Image

# ---------------------------------------------------------------------------
# Constants & Engine Limits
# ---------------------------------------------------------------------------
MAX_TEXTURE_DIMENSION: Final[int] = 8192
MAX_GRID_CELLS: Final[int] = 100
MAX_GRID_AXIS_CELLS: Final[int] = 10
CENTIMETERS_PER_INCH: Final[float] = 2.54

DEFAULT_CARD_THICKNESS_CM: Final[float] = 0.05
DEFAULT_GUIDEBOOK_THICKNESS_CM: Final[float] = 0.03
DEFAULT_CARD_MODEL: Final[str] = "Rounded"
DEFAULT_GUIDEBOOK_MODEL: Final[str] = "Square"


# ---------------------------------------------------------------------------
# Domain Models (Data Transfer & Value Objects)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PhysicalDimensions:
    width: float
    height: float
    thickness: float
    model: str


@dataclass(frozen=True)
class GridDimensions:
    cols: int
    rows: int

    @property
    def capacity(self) -> int:
        return self.cols * self.rows


@dataclass(frozen=True)
class CardPair:
    front_path: Path
    back_path: Path
    index: int


@dataclass(frozen=True)
class DeckMetadata:
    universe: str
    category: str
    deck_name: str
    description: str
    is_guidebook: bool
    profile_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Environment & Configuration Manager
# ---------------------------------------------------------------------------
class ConfigurationManager:
    """Manages application configuration, path resolution, and Fail-Fast validation."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config.json"

        if not self.config_path.exists():
            self._fail_fast(f"Configuration file does not exist: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                self.data: dict[str, Any] = json.load(file)
        except Exception as exc:
            self._fail_fast(f"Failed to parse {self.config_path}: {exc}")

        self.dpi: int = self.data.get("dpi", 200)
        if self.dpi <= 0:
            self._fail_fast(f"DPI must be a positive integer. Provided: {self.dpi}")

        dirs_cfg = self.data.get("dirs", {})
        self.input_dir = self.base_dir / dirs_cfg.get("input", "_INPUT")
        self.output_dir = self.base_dir / dirs_cfg.get("output", "_OUTPUT")

        if not self.output_dir.exists():
            self._fail_fast(f"Extracted cards directory (_OUTPUT) not found at: {self.output_dir}")

        ttpg_cfg = self.data.get("ttpg", {})
        self.package_name: str = ttpg_cfg.get("package_name", "The Story Engine Universe")
        pkg_root = self.base_dir / ttpg_cfg.get("output_dir", "_PACKAGE")
        self.package_dest = pkg_root / self.package_name

        self.templates_dir = self.package_dest / "Templates"
        self.textures_dir = self.package_dest / "Textures"

        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.textures_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fail_fast(message: str) -> None:
        print(f"[FAIL-FAST] {message}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Context & Profile Resolver (Cascading Overrides)
# ---------------------------------------------------------------------------
class ContextResolver:
    """Resolves hierarchical configuration overrides (deck.json -> config.json rules -> defaults)."""

    def __init__(self, config_mgr: ConfigurationManager) -> None:
        self.cfg = config_mgr.data
        self.input_dir = config_mgr.input_dir
        self.output_dir = config_mgr.output_dir

    def resolve_deck_context(self, deck_dir: Path) -> tuple[DeckMetadata, dict[str, Any]]:
        rel_parts = deck_dir.relative_to(self.output_dir).parts
        universe = rel_parts[0] if len(rel_parts) > 1 else "Core"
        category = rel_parts[1] if len(rel_parts) > 2 else ""
        deck_name = rel_parts[-1]
        is_guidebook = "guidebook" in deck_name.lower() or "instruction" in deck_name.lower()

        overrides = self._collect_hierarchical_overrides(deck_dir)

        # Match against predefined rules if profile not explicitly specified in deck.json
        matched_profile = overrides.get("profile")
        if not matched_profile:
            matched_profile = self._match_rule_profile(deck_name, is_guidebook)

        metadata = DeckMetadata(
            universe=overrides.get("meta", {}).get("universe", universe),
            category=overrides.get("meta", {}).get("category", category),
            deck_name=overrides.get("meta", {}).get("deck_name", deck_name),
            description=overrides.get("meta", {}).get(
                "description",
                f"Deck from '{universe}'" + (f" ({category})" if category else ""),
            ),
            is_guidebook=is_guidebook,
            profile_name=matched_profile,
        )

        return metadata, overrides

    def _collect_hierarchical_overrides(self, deck_dir: Path) -> dict[str, Any]:
        """Cascades overrides from parent directories up to input root."""
        rel_path = deck_dir.relative_to(self.output_dir)
        check_path = self.input_dir / rel_path
        hierarchy: list[Path] = []

        curr = check_path
        while curr != self.input_dir.parent:
            deck_json = curr / "deck.json"
            if deck_json.exists():
                hierarchy.append(deck_json)
            curr = curr.parent

        # Merge from top-level to closest leaf
        merged: dict[str, Any] = {}
        for config_file in reversed(hierarchy):
            try:
                with open(config_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    merged.update(data)
            except Exception as exc:
                print(f"[WARN] Failed to read {config_file}: {exc}", file=sys.stderr)

        return merged

    def _match_rule_profile(self, deck_name: str, is_guidebook: bool) -> str:
        for rule in self.cfg.get("rules", []):
            pattern = rule.get("pattern", "")
            if fnmatch.fnmatch(deck_name, pattern) or fnmatch.fnmatch(f"{deck_name}.pdf", pattern):
                return rule.get("profile", "")

        if is_guidebook:
            return "full_page_duplex"
        return self.cfg.get("default_profile", "story_engine_standard")


# ---------------------------------------------------------------------------
# Physics & Dimension Engine (Separation of Concerns)
# ---------------------------------------------------------------------------
class PhysicsEngine:
    """Calculates physical attributes deterministically without hardcoded magic numbers."""

    def __init__(self, config_mgr: ConfigurationManager) -> None:
        self.dpi = config_mgr.dpi
        self.profiles = config_mgr.data.get("profiles", {})

    def compute(
        self,
        pixel_width: int,
        pixel_height: int,
        metadata: DeckMetadata,
        overrides: dict[str, Any],
    ) -> PhysicalDimensions:
        # Deterministic formula: size_cm = (pixels / dpi) * 2.54
        calculated_width = round((pixel_width / self.dpi) * CENTIMETERS_PER_INCH, 4)
        calculated_height = round((pixel_height / self.dpi) * CENTIMETERS_PER_INCH, 4)

        profile = self.profiles.get(metadata.profile_name, {})

        # 1. Width / Height: overrides -> profile -> calculated from image pixels
        width = (
            overrides.get("card_width_cm")
            or profile.get("card_width_cm")
            or calculated_width
        )
        height = (
            overrides.get("card_height_cm")
            or profile.get("card_height_cm")
            or calculated_height
        )

        # 2. Thickness: overrides -> profile -> domain defaults
        default_thickness = (
            DEFAULT_GUIDEBOOK_THICKNESS_CM
            if metadata.is_guidebook
            else DEFAULT_CARD_THICKNESS_CM
        )
        thickness = (
            overrides.get("thickness_cm")
            or profile.get("thickness_cm")
            or default_thickness
        )

        # 3. Model: overrides -> profile -> domain defaults
        default_model = (
            DEFAULT_GUIDEBOOK_MODEL
            if metadata.is_guidebook
            else DEFAULT_CARD_MODEL
        )
        model = overrides.get("model") or profile.get("model") or default_model

        return PhysicalDimensions(
            width=float(width),
            height=float(height),
            thickness=float(thickness),
            model=str(model),
        )


# ---------------------------------------------------------------------------
# Grid & Atlas Layout Optimizer
# ---------------------------------------------------------------------------
class GridLayoutOptimizer:
    """Computes optimal grid layouts adhering strictly to TTPG and GPU texture boundaries."""

    @staticmethod
    def calculate_bounds(card_w: int, card_h: int) -> tuple[int, int]:
        max_cols = max(1, min(MAX_GRID_AXIS_CELLS, MAX_TEXTURE_DIMENSION // card_w))
        max_rows = max(1, min(MAX_GRID_AXIS_CELLS, MAX_TEXTURE_DIMENSION // card_h))

        if max_cols * max_rows == 0:
            print(
                f"[FAIL-FAST] Card dimensions ({card_w}x{card_h} px) exceed maximum texture boundary ({MAX_TEXTURE_DIMENSION} px).",
                file=sys.stderr,
            )
            sys.exit(1)

        return max_cols, max_rows

    @classmethod
    def optimize(cls, total_cards: int, card_w: int, card_h: int) -> GridDimensions:
        max_cols, max_rows = cls.calculate_bounds(card_w, card_h)
        max_capacity = min(MAX_GRID_CELLS, max_cols * max_rows)

        # For multi-sheet decks, enforce uniform maximum grid dimensions across all sheets
        if total_cards > max_capacity:
            return GridDimensions(cols=max_cols, rows=max_rows)

        best_c, best_r = max_cols, max_rows
        min_waste = float("inf")
        min_aspect_diff = float("inf")

        for c in range(1, max_cols + 1):
            for r in range(1, max_rows + 1):
                cell_count = c * r
                if cell_count >= total_cards and cell_count <= MAX_GRID_CELLS:
                    waste = cell_count - total_cards
                    aspect_diff = abs(c - r)
                    if waste < min_waste or (waste == min_waste and aspect_diff < min_aspect_diff):
                        min_waste = waste
                        min_aspect_diff = aspect_diff
                        best_c, best_r = c, r

        return GridDimensions(cols=best_c, rows=best_r)


# ---------------------------------------------------------------------------
# Texture Atlas Builder
# ---------------------------------------------------------------------------
class TextureAtlasBuilder:
    """Builds and serializes front and back texture sheets in lockstep."""

    def __init__(self, textures_dir: Path) -> None:
        self.textures_dir = textures_dir

    def build_sheet(
        self,
        chunk: list[CardPair],
        grid: GridDimensions,
        card_w: int,
        card_h: int,
        front_filename: str,
        back_filename: str,
    ) -> tuple[Path, Path]:
        sheet_w = grid.cols * card_w
        sheet_h = grid.rows * card_h

        atlas_front = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
        atlas_back = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))

        for idx, pair in enumerate(chunk):
            col = idx % grid.cols
            row = idx // grid.cols
            pos = (col * card_w, row * card_h)

            with Image.open(pair.front_path) as im_f:
                atlas_front.paste(im_f, pos)

            with Image.open(pair.back_path) as im_b:
                atlas_back.paste(im_b, pos)

        front_path = self.textures_dir / front_filename
        back_path = self.textures_dir / back_filename

        atlas_front.save(front_path)
        atlas_back.save(back_path)

        return front_path, back_path


# ---------------------------------------------------------------------------
# Template Factory (TTPG Unreal Engine Schema)
# ---------------------------------------------------------------------------
class TemplateFactory:
    """Constructs Tabletop Playground Card templates with native multi-sheet support."""

    @staticmethod
    def create_card_template(
        guid: str,
        meta: DeckMetadata,
        physics: PhysicalDimensions,
        grid: GridDimensions,
        front_textures: list[str],
        back_textures: list[str],
        total_cards: int,
        package_name: str,
        source_dpi: int,
    ) -> dict[str, Any]:
        if not front_textures or not back_textures:
            print("[FAIL-FAST] Attempted to create template without textures.", file=sys.stderr)
            sys.exit(1)

        display_name = (
            f"[{meta.universe}] {meta.deck_name}"
            if meta.universe.lower() not in meta.deck_name.lower()
            else meta.deck_name
        )
        tooltip = f"{meta.universe} • {meta.deck_name}"

        if meta.is_guidebook:
            tooltip += " (Guidebook)"
            description = (
                f"Official Guidebook / Rulesheet for '{meta.deck_name}'.\n"
                f"Universe: {meta.universe}.\nPages: {total_cards}."
            )
        else:
            description = (
                f"Expansion deck for {meta.universe}: '{meta.deck_name}'.\n"
                f"Total cards in set: {total_cards}."
            )

        structured_metadata = json.dumps(
            {
                "system": package_name,
                "universe": meta.universe,
                "category": meta.category,
                "deck": meta.deck_name,
                "is_guidebook": meta.is_guidebook,
                "card_count": total_cards,
                "sheet_count": len(front_textures),
                "source_dpi": source_dpi,
                "dimensions_cm": {
                    "width": physics.width,
                    "height": physics.height,
                    "thickness": physics.thickness,
                },
            },
            ensure_ascii=False,
        )

        return {
            "Type": "Card",
            "GUID": guid,
            "Name": display_name,
            "ScriptName": "",
            "Metadata": structured_metadata,
            "TooltipName": tooltip,
            "Description": description,
            "CollisionType": "Regular",
            "Friction": 0.7,
            "Restitution": 0.0,
            "Density": 0.5,
            "SurfaceType": "Cardboard",
            "Roughness": 1.0,
            "Metallic": 0.0,
            "PrimaryColor": {"R": 244, "G": 244, "B": 244},
            "SecondaryColor": {"R": 0, "G": 0, "B": 0},
            "PrimaryColorFromOwner": False,
            "SecondaryColorFromOwner": False,
            "Flippable": True,
            "AutoStraighten": False,
            "ShouldSnap": True,
            "Blueprint": "",
            "Models": [],
            "Collision": [],
            "Lights": [],
            "SnapPointsGlobal": False,
            "SnapPoints": [],
            "UseCustomZoomViewDirection": False,
            "ZoomViewDirection": {"X": 0.0, "Y": 0.0, "Z": 1.0},
            "GroundAccessibility": "ZoomAndContext",
            "Tags": [meta.universe, "Guidebook" if meta.is_guidebook else "Deck"],
            "TemplateUIs": [],
            "uiOptions": [],
            "FrontTexture": front_textures[0],
            "BackTexture": back_textures[0],
            "ExtraFrontTextures": front_textures[1:] if len(front_textures) > 1 else [],
            "ExtraBackTextures": back_textures[1:] if len(back_textures) > 1 else [],
            "HiddenTexture": "",
            "BackIndex": -3,
            "HiddenIndex": -3,
            "NumHorizontal": grid.cols,
            "NumVertical": grid.rows,
            "Width": physics.width,
            "Height": physics.height,
            "Thickness": physics.thickness,
            "HiddenInHand": True,
            "UsedWithCardHolders": True,
            "CanStack": True,
            "CardFrontColorMode": "None",
            "CardBackColorMode": "None",
            "CardSideColorMode": "None",
            "FrontTextureOverrideExposed": False,
            "AllowFlippedInStack": False,
            "MirrorBack": False,
            "EmissiveFront": False,
            "Model": physics.model,
            "CardType": "Card",
            "Indices": list(range(total_cards)),
            "CardNames": {},
            "CardMetadata": {},
            "CardTags": {},
        }


# ---------------------------------------------------------------------------
# Package Orchestrator / Pipeline Coordinator
# ---------------------------------------------------------------------------
class PackageOrchestrator:
    """Coordinates card pair validation, atlas compilation, and manifest production."""

    def __init__(self, config_mgr: ConfigurationManager) -> None:
        self.config_mgr = config_mgr
        self.context_resolver = ContextResolver(config_mgr)
        self.physics_engine = PhysicsEngine(config_mgr)
        self.atlas_builder = TextureAtlasBuilder(config_mgr.textures_dir)

    @staticmethod
    def sanitize_identifier(name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")

    def validate_and_collect_pairs(self, deck_dir: Path) -> list[CardPair]:
        front_files = sorted(
            deck_dir.glob("card_*_front.png"),
            key=lambda p: int(re.search(r"card_(\d+)_front", p.name).group(1)),  # type: ignore[union-attr]
        )

        pairs: list[CardPair] = []
        for front in front_files:
            match = re.search(r"card_(\d+)_front", front.name)
            if not match:
                print(f"[FAIL-FAST] Filename violates schema: {front.name}", file=sys.stderr)
                sys.exit(1)

            idx_str = match.group(1)
            back = deck_dir / f"card_{idx_str}_back.png"

            if not back.exists():
                print(
                    f"[FAIL-FAST] Missing duplex back side: expected {back.name} for {front.name}",
                    file=sys.stderr,
                )
                sys.exit(1)

            pairs.append(CardPair(front_path=front, back_path=back, index=int(idx_str)))

        return pairs

    def process_deck(self, deck_dir: Path) -> None:
        pairs = self.validate_and_collect_pairs(deck_dir)
        if not pairs:
            return

        deck_name = deck_dir.name
        meta, overrides = self.context_resolver.resolve_deck_context(deck_dir)

        # Dimension integrity verification
        with Image.open(pairs[0].front_path) as sample:
            card_w, card_h = sample.size

        for pair in pairs:
            with Image.open(pair.front_path) as f_img:
                if f_img.size != (card_w, card_h):
                    print(
                        f"[FAIL-FAST] Dimension anomaly in {deck_name}: {pair.front_path.name} "
                        f"has size {f_img.size}, expected {(card_w, card_h)}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            with Image.open(pair.back_path) as b_img:
                if b_img.size != (card_w, card_h):
                    print(
                        f"[FAIL-FAST] Dimension anomaly in {deck_name}: {pair.back_path.name} "
                        f"has size {b_img.size}, expected {(card_w, card_h)}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

        total_cards = len(pairs)
        grid = GridLayoutOptimizer.optimize(total_cards, card_w, card_h)

        chunks = [
            pairs[i : i + grid.capacity]
            for i in range(0, total_cards, grid.capacity)
        ]
        total_sheets = len(chunks)

        print(
            f"\n[PACKAGE] Deck: {deck_name} | Total Cards: {total_cards} | "
            f"Grid: {grid.cols}x{grid.rows} | Sheets: {total_sheets}"
        )

        clean_name = self.sanitize_identifier(deck_name)
        front_textures: list[str] = []
        back_textures: list[str] = []

        for sheet_idx, chunk in enumerate(chunks, start=1):
            suffix = f"_{sheet_idx:02d}" if total_sheets > 1 else ""
            f_name = f"{clean_name}{suffix}_front.png"
            b_name = f"{clean_name}{suffix}_back.png"

            self.atlas_builder.build_sheet(chunk, grid, card_w, card_h, f_name, b_name)
            front_textures.append(f_name)
            back_textures.append(b_name)
            print(f"  [+] Sheet {sheet_idx}/{total_sheets} baked: {f_name}")

        physics = self.physics_engine.compute(card_w, card_h, meta, overrides)
        card_guid = uuid.uuid4().hex.upper()

        template_payload = TemplateFactory.create_card_template(
            guid=card_guid,
            meta=meta,
            physics=physics,
            grid=grid,
            front_textures=front_textures,
            back_textures=back_textures,
            total_cards=total_cards,
            package_name=self.config_mgr.package_name,
            source_dpi=self.config_mgr.dpi,
        )

        template_file = self.config_mgr.templates_dir / f"{card_guid}Card.json"
        with open(template_file, "w", encoding="utf-8") as file:
            json.dump(template_payload, file, indent=2)

        print(f"  [+] Unified Deck Template generated: {template_file.name}")

    def generate_manifest(self) -> None:
        manifest_path = self.config_mgr.package_dest / "Manifest.json"
        manifest_guid = uuid.uuid4().hex.upper()
        payload = {
            "Name": self.config_mgr.package_name,
            "Version": "1",
            "GUID": manifest_guid,
        }
        with open(manifest_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        print(f"[OK] Manifest.json written with Package GUID: {manifest_guid}")

    def run(self) -> None:
        deck_directories: list[Path] = [
            d for d in sorted(self.config_mgr.output_dir.rglob("*"))
            if d.is_dir() and any(d.glob("card_*_front.png"))
        ]

        if not deck_directories:
            print(
                f"[FAIL-FAST] No extracted decks discovered in: {self.config_mgr.output_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"[*] Compiling package: '{self.config_mgr.package_name}'")
        print(f"[*] Discovered {len(deck_directories)} deck folder(s).")

        self.generate_manifest()

        for deck_dir in deck_directories:
            self.process_deck(deck_dir)

        print(f"\n[SUCCESS] Package successfully compiled: {self.config_mgr.package_dest}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    base_dir = Path(__file__).resolve().parent
    config_mgr = ConfigurationManager(base_dir)
    orchestrator = PackageOrchestrator(config_mgr)
    orchestrator.run()


if __name__ == "__main__":
    main()