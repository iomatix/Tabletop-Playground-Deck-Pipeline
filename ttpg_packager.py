"""
Tabletop Playground (TTPG) Package & Deck Compiler.

Handles multi-sheet texture atlas stitching, dynamic physics calculation
from DPI and pixel dimensions, contract-driven metadata resolution (via deck_meta.json),
hierarchical context-aware naming, safe clean-slate package state management,
and UV-compliant partitioned stacks.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image

# ---------------------------------------------------------------------------
# Constants & Engine Limits
# ---------------------------------------------------------------------------
MAX_TEXTURE_DIMENSION: Final[int] = 8192
MAX_GRID_CELLS: Final[int] = 100
MAX_GRID_AXIS_CELLS: Final[int] = 10
CENTIMETERS_PER_INCH: Final[float] = 2.54
MAX_JITTER_TOLERANCE_PX: Final[int] = 2

DEFAULT_CARD_THICKNESS_CM: Final[float] = 0.05
DEFAULT_DOCUMENT_THICKNESS_CM: Final[float] = 0.03
DEFAULT_CARD_MODEL: Final[str] = "Rounded"
DEFAULT_DOCUMENT_MODEL: Final[str] = "Square"

DIR_TEMPLATES: Final[str] = "Templates"
DIR_TEXTURES: Final[str] = "Textures"


# ---------------------------------------------------------------------------
# Domain Models
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
    package_context: str
    deck_name: str
    display_name: str
    description: str
    is_document: bool
    profile_name: str


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

        self.templates_dir = self.package_dest / DIR_TEMPLATES
        self.textures_dir = self.package_dest / DIR_TEXTURES

    def ensure_clean_package_staging(self) -> None:
        """Purges old compiled assets safely without removing locked root directories."""
        for root_dir in (self.templates_dir, self.textures_dir):
            root_dir.mkdir(parents=True, exist_ok=True)
            for item in root_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except Exception as exc:
                    print(f"[WARN] Could not remove stale asset {item.name}: {exc}", file=sys.stderr)

    @staticmethod
    def _fail_fast(message: str) -> None:
        print(f"[FAIL-FAST] {message}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Context & Contract Resolver
# ---------------------------------------------------------------------------
class ContextResolver:
    """Resolves hierarchical directory paths and deck_meta.json contracts."""

    def __init__(self, config_mgr: ConfigurationManager) -> None:
        self.cfg = config_mgr.data
        self.input_dir = config_mgr.input_dir
        self.output_dir = config_mgr.output_dir

    def resolve_deck_context(self, deck_dir: Path) -> tuple[DeckMetadata, dict[str, Any]]:
        rel_parts = deck_dir.relative_to(self.output_dir).parts

        package_context = rel_parts[0] if len(rel_parts) > 1 else ""
        raw_deck_name = rel_parts[-1]

        contract_path = deck_dir / "deck_meta.json"
        is_document = False
        contract_profile = None

        if contract_path.exists():
            try:
                with open(contract_path, "r", encoding="utf-8") as file:
                    contract_data = json.load(file)
                    is_document = contract_data.get("item_type") == "document"
                    contract_profile = contract_data.get("profile")
            except Exception as exc:
                print(f"[WARN] Failed to read contract {contract_path}: {exc}", file=sys.stderr)

        overrides = self._collect_hierarchical_overrides(deck_dir)

        profile_name = (
            overrides.get("profile")
            or contract_profile
            or ("full_page_duplex" if is_document else self.cfg.get("default_profile", "story_engine_standard"))
        )

        universe = overrides.get("meta", {}).get("universe", package_context or "Core")
        deck_name = overrides.get("meta", {}).get("deck_name", raw_deck_name)

        if package_context and package_context.lower() not in deck_name.lower():
            display_name = f"[{package_context}] {deck_name}"
        else:
            display_name = deck_name

        metadata = DeckMetadata(
            universe=universe,
            package_context=package_context,
            deck_name=deck_name,
            display_name=display_name,
            description=overrides.get("meta", {}).get(
                "description",
                f"{'Document' if is_document else 'Deck'} from '{package_context or universe}': {deck_name}",
            ),
            is_document=is_document,
            profile_name=profile_name,
        )

        return metadata, overrides

    def _collect_hierarchical_overrides(self, deck_dir: Path) -> dict[str, Any]:
        rel_path = deck_dir.relative_to(self.output_dir)
        check_path = self.input_dir / rel_path
        hierarchy: list[Path] = []

        curr = check_path
        while curr != self.input_dir.parent:
            deck_json = curr / "deck.json"
            if deck_json.exists():
                hierarchy.append(deck_json)
            curr = curr.parent

        merged: dict[str, Any] = {}
        for config_file in reversed(hierarchy):
            try:
                with open(config_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    merged.update(data)
            except Exception as exc:
                print(f"[WARN] Failed to read {config_file}: {exc}", file=sys.stderr)

        return merged


# ---------------------------------------------------------------------------
# Physics & Dimension Engine
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
        calculated_width = round((pixel_width / self.dpi) * CENTIMETERS_PER_INCH, 4)
        calculated_height = round((pixel_height / self.dpi) * CENTIMETERS_PER_INCH, 4)

        profile = self.profiles.get(metadata.profile_name, {})

        raw_w = overrides.get("card_width_cm") or profile.get("card_width_cm")
        width = calculated_width if raw_w in (None, "auto") else raw_w

        raw_h = overrides.get("card_height_cm") or profile.get("card_height_cm")
        height = calculated_height if raw_h in (None, "auto") else raw_h

        default_thickness = DEFAULT_DOCUMENT_THICKNESS_CM if metadata.is_document else DEFAULT_CARD_THICKNESS_CM
        thickness = overrides.get("thickness_cm") or profile.get("thickness_cm") or default_thickness

        default_model = DEFAULT_DOCUMENT_MODEL if metadata.is_document else DEFAULT_CARD_MODEL
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
    """Computes optimal grid layouts adhering strictly to TTPG texture limits."""

    @staticmethod
    def calculate_bounds(card_w: int, card_h: int) -> tuple[int, int]:
        max_cols = max(1, min(MAX_GRID_AXIS_CELLS, MAX_TEXTURE_DIMENSION // card_w))
        max_rows = max(1, min(MAX_GRID_AXIS_CELLS, MAX_TEXTURE_DIMENSION // card_h))

        if max_cols * max_rows == 0:
            print(
                f"[FAIL-FAST] Item dimensions ({card_w}x{card_h} px) exceed maximum boundary ({MAX_TEXTURE_DIMENSION} px).",
                file=sys.stderr,
            )
            sys.exit(1)

        return max_cols, max_rows

    @classmethod
    def optimize(cls, total_cards: int, card_w: int, card_h: int) -> GridDimensions:
        max_cols, max_rows = cls.calculate_bounds(card_w, card_h)
        max_capacity = min(MAX_GRID_CELLS, max_cols * max_rows)

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
    """Builds and serializes front and back texture sheets with auto-normalization."""

    def __init__(self, textures_dir: Path) -> None:
        self.textures_dir = textures_dir

    def build_sheet(
        self,
        chunk: list[CardPair],
        grid: GridDimensions,
        canonical_w: int,
        canonical_h: int,
        front_filename: str,
        back_filename: str,
    ) -> tuple[Path, Path]:
        sheet_w = grid.cols * canonical_w
        sheet_h = grid.rows * canonical_h

        atlas_front = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
        atlas_back = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))

        for idx, pair in enumerate(chunk):
            col = idx % grid.cols
            row = idx // grid.cols
            pos = (col * canonical_w, row * canonical_h)

            with Image.open(pair.front_path) as im_f:
                if im_f.size != (canonical_w, canonical_h):
                    im_f = im_f.resize((canonical_w, canonical_h), Image.Resampling.LANCZOS)
                atlas_front.paste(im_f, pos)

            with Image.open(pair.back_path) as im_b:
                if im_b.size != (canonical_w, canonical_h):
                    im_b = im_b.resize((canonical_w, canonical_h), Image.Resampling.LANCZOS)
                atlas_back.paste(im_b, pos)

        front_path = self.textures_dir / front_filename
        back_path = self.textures_dir / back_filename

        atlas_front.save(front_path)
        atlas_back.save(back_path)

        return front_path, back_path


# ---------------------------------------------------------------------------
# Template Factory
# ---------------------------------------------------------------------------
class TemplateFactory:
    """Constructs UV-compliant TTPG Card templates bounded per atlas sheet."""

    @staticmethod
    def create_card_template(
        guid: str,
        meta: DeckMetadata,
        physics: PhysicalDimensions,
        grid: GridDimensions,
        front_texture: str,
        back_texture: str,
        chunk: list[CardPair],
        part_index: int,
        total_parts: int,
        total_deck_items: int,
        package_name: str,
        source_dpi: int,
    ) -> dict[str, Any]:
        chunk_items = len(chunk)

        part_suffix = f" (Part {part_index})" if total_parts > 1 else ""
        display_name = f"{meta.display_name}{part_suffix}"
        tooltip = f"{meta.package_context or meta.universe} • {meta.deck_name}{part_suffix}"

        if meta.is_document:
            description = (
                f"Official document/rulesheet: '{meta.deck_name}'{part_suffix}.\n"
                f"Package: {meta.package_context or meta.universe}.\nPages: {chunk_items}."
            )
        else:
            description = (
                f"Card deck: '{meta.deck_name}'{part_suffix}.\n"
                f"Package: {meta.package_context or meta.universe}.\n"
                f"Cards in this stack: {chunk_items} (Total: {total_deck_items})."
            )

        card_names: dict[str, str] = {}
        card_metadata: dict[str, str] = {}

        for slot_idx, pair in enumerate(chunk):
            slot_key = str(slot_idx)
            if meta.is_document:
                card_names[slot_key] = f"{meta.deck_name} - Page {pair.index}"
                card_metadata[slot_key] = json.dumps(
                    {
                        "deck": meta.deck_name,
                        "page": pair.index,
                        "is_document": True,
                    },
                    ensure_ascii=False,
                )
            else:
                card_names[slot_key] = f"{meta.deck_name} #{pair.index:03d}"
                card_metadata[slot_key] = json.dumps(
                    {
                        "card_id": pair.index,
                        "deck": meta.deck_name,
                        "package": meta.package_context,
                        "part": part_index,
                        "file": pair.front_path.name,
                    },
                    ensure_ascii=False,
                )

        structured_metadata = json.dumps(
            {
                "system": package_name,
                "universe": meta.universe,
                "package_context": meta.package_context,
                "deck": meta.deck_name,
                "part": part_index,
                "total_parts": total_parts,
                "is_document": meta.is_document,
                "item_count": chunk_items,
                "total_deck_items": total_deck_items,
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
            "Tags": [meta.universe, "Document" if meta.is_document else "Deck"],
            "TemplateUIs": [],
            "uiOptions": [],
            "FrontTexture": front_texture,
            "BackTexture": back_texture,
            "ExtraFrontTextures": [],
            "ExtraBackTextures": [],
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
            "Indices": list(range(chunk_items)),
            "CardNames": card_names,
            "CardMetadata": card_metadata,
            "CardTags": {},
        }


# ---------------------------------------------------------------------------
# Package Orchestrator
# ---------------------------------------------------------------------------
class PackageOrchestrator:
    """Coordinates card pair validation, atlas compilation, and manifests."""

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

    def _resolve_canonical_dimensions(self, deck_name: str, pairs: list[CardPair]) -> tuple[int, int]:
        observed_sizes: list[tuple[int, int]] = []
        for pair in pairs:
            with Image.open(pair.front_path) as f_img:
                observed_sizes.append(f_img.size)
            with Image.open(pair.back_path) as b_img:
                observed_sizes.append(b_img.size)

        canonical_w, canonical_h = Counter(observed_sizes).most_common(1)[0][0]

        for pair in pairs:
            for _, side_path in (("front", pair.front_path), ("back", pair.back_path)):
                with Image.open(side_path) as img:
                    dw = abs(img.width - canonical_w)
                    dh = abs(img.height - canonical_h)
                    if dw > MAX_JITTER_TOLERANCE_PX or dh > MAX_JITTER_TOLERANCE_PX:
                        print(
                            f"[FAIL-FAST] Dimension anomaly in {deck_name}: {side_path.name} "
                            f"has size {img.size}, expected {canonical_w}x{canonical_h} px.",
                            file=sys.stderr,
                        )
                        sys.exit(1)

        return canonical_w, canonical_h

    def process_deck(self, deck_dir: Path) -> None:
        pairs = self.validate_and_collect_pairs(deck_dir)
        if not pairs:
            return

        meta, overrides = self.context_resolver.resolve_deck_context(deck_dir)
        card_w, card_h = self._resolve_canonical_dimensions(meta.deck_name, pairs)

        total_items = len(pairs)
        grid = GridLayoutOptimizer.optimize(total_items, card_w, card_h)

        chunks = [pairs[i : i + grid.capacity] for i in range(0, total_items, grid.capacity)]
        total_parts = len(chunks)

        print(
            f"\n[PACKAGE] {meta.display_name} | Items: {total_items} | "
            f"Type: {'Document' if meta.is_document else 'Deck'} | Grid: {grid.cols}x{grid.rows} | Parts: {total_parts}"
        )

        prefix_parts = [meta.package_context, meta.deck_name] if meta.package_context else [meta.deck_name]
        clean_prefix = self.sanitize_identifier("_".join(prefix_parts))

        physics = self.physics_engine.compute(card_w, card_h, meta, overrides)

        for part_idx, chunk in enumerate(chunks, start=1):
            suffix = f"_{part_idx:02d}" if total_parts > 1 else ""
            f_name = f"{clean_prefix}{suffix}_front.png"
            b_name = f"{clean_prefix}{suffix}_back.png"

            self.atlas_builder.build_sheet(chunk, grid, card_w, card_h, f_name, b_name)
            print(f"  [+] Atlas baked: {f_name}")

            card_guid = uuid.uuid4().hex.upper()
            template_payload = TemplateFactory.create_card_template(
                guid=card_guid,
                meta=meta,
                physics=physics,
                grid=grid,
                front_texture=f_name,
                back_texture=b_name,
                chunk=chunk,
                part_index=part_idx,
                total_parts=total_parts,
                total_deck_items=total_items,
                package_name=self.config_mgr.package_name,
                source_dpi=self.config_mgr.dpi,
            )

            template_file = self.config_mgr.templates_dir / f"{card_guid}Card.json"
            with open(template_file, "w", encoding="utf-8") as file:
                json.dump(template_payload, file, indent=2)

            name_info = template_payload["Name"]
            print(f"  [+] Template generated: {template_file.name} -> '{name_info}' ({len(chunk)} cards)")

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
            d for d in sorted(self.config_mgr.output_dir.rglob("*")) if d.is_dir() and any(d.glob("card_*_front.png"))
        ]

        if not deck_directories:
            print(
                f"[FAIL-FAST] No extracted items discovered in: {self.config_mgr.output_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

        self.config_mgr.ensure_clean_package_staging()

        print(f"[*] Compiling package: '{self.config_mgr.package_name}'")
        print(f"[*] Discovered {len(deck_directories)} item folder(s).")

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
