import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

if not CONFIG_PATH.exists():
    print(f"[FAIL-FAST] Missing configuration file: {CONFIG_PATH}", file=sys.stderr)
    sys.exit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

ttpg_cfg = cfg.get("ttpg", {})
package_name = ttpg_cfg.get("package_name", "The Story Engine Universe")
output_root = BASE_DIR / cfg.get("dirs", {}).get("output", "_OUTPUT")
package_dest = BASE_DIR / ttpg_cfg.get("output_dir", "_PACKAGE") / package_name

templates_dir = package_dest / "Templates"
textures_dir = package_dest / "Textures"

for folder in [templates_dir, textures_dir]:
    folder.mkdir(parents=True, exist_ok=True)

MAX_TEX_DIM = 8192
MAX_GRID_CELLS = 100

def sanitize_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name).strip('_')

def calculate_optimal_grid(n: int, card_w: int, card_h: int) -> tuple[int, int]:
    max_cols = max(1, min(10, MAX_TEX_DIM // card_w))
    max_rows = max(1, min(10, MAX_TEX_DIM // card_h))

    best_c, best_r = max_cols, max_rows
    min_waste = float("inf")
    min_aspect_diff = float("inf")

    for c in range(1, max_cols + 1):
        for r in range(1, max_rows + 1):
            if c * r >= n:
                waste = (c * r) - n
                aspect_diff = abs(c - r)
                if waste < min_waste:
                    min_waste = waste
                    min_aspect_diff = aspect_diff
                    best_c, best_r = c, r
                elif waste == min_waste and aspect_diff < min_aspect_diff:
                    min_aspect_diff = aspect_diff
                    best_c, best_r = c, r

    return best_c, best_r

def build_card_template(
    guid: str,
    name: str,
    front_tex: str,
    back_tex: str,
    cols: int,
    rows: int,
    indices: list[int],
    is_guidebook: bool
) -> dict:
    width = 21.59 if is_guidebook else 7.62
    height = 27.94 if is_guidebook else 7.62
    thickness = 0.04 if is_guidebook else 0.05
    model = "Square" if is_guidebook else "Rounded"

    return {
        "Type": "Card",
        "GUID": guid,
        "Name": name,
        "ScriptName": "",
        "Metadata": "",
        "TooltipName": "",
        "Description": "",
        "CollisionType": "Regular",
        "Friction": 0.7,
        "Restitution": 0,
        "Density": 0.5,
        "SurfaceType": "Cardboard",
        "Roughness": 1,
        "Metallic": 0,
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
        "ZoomViewDirection": {"X": 0, "Y": 0, "Z": 1},
        "GroundAccessibility": "ZoomAndContext",
        "Tags": [],
        "TemplateUIs": [],
        "uiOptions": [],
        "FrontTexture": front_tex,
        "BackTexture": back_tex,
        "HiddenTexture": "",
        "BackIndex": -3,
        "HiddenIndex": -3,
        "NumHorizontal": cols,
        "NumVertical": rows,
        "Width": width,
        "Height": height,
        "Thickness": thickness,
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
        "Model": model,
        "CardType": "Card",
        "Indices": indices,
        "CardNames": {},
        "CardMetadata": {},
        "CardTags": {}
    }

def find_deck_directories(root: Path) -> list[Path]:
    deck_dirs = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() and any(path.glob("card_*_front.png")):
            deck_dirs.append(path)
    return deck_dirs

def process_deck(deck_dir: Path):
    front_files = sorted(
        deck_dir.glob("card_*_front.png"),
        key=lambda p: int(re.search(r"card_(\d+)_front", p.name).group(1))
    )

    if not front_files:
        return

    card_pairs = []
    for f in front_files:
        cid = re.search(r"card_(\d+)_front", f.name).group(1)
        b = deck_dir / f"card_{cid}_back.png"
        if not b.exists():
            print(f"[FAIL-FAST] Missing back side for card: {f.name}", file=sys.stderr)
            sys.exit(1)
        card_pairs.append((f, b))

    deck_name = deck_dir.name
    is_guidebook = "guidebook" in deck_name.lower() or "guidebook" in str(deck_dir).lower()

    with Image.open(card_pairs[0][0]) as sample_img:
        card_w, card_h = sample_img.size

    max_c = max(1, min(10, MAX_TEX_DIM // card_w))
    max_r = max(1, min(10, MAX_TEX_DIM // card_h))
    max_per_sheet = min(MAX_GRID_CELLS, max_c * max_r)

    total_cards = len(card_pairs)
    chunks = [card_pairs[i:i + max_per_sheet] for i in range(0, total_cards, max_per_sheet)]

    print(f"\n[PACKAGE] {deck_name} | Cards: {total_cards} | Format: {'Guidebook A4' if is_guidebook else 'Card 3x3'}")

    clean_deck = sanitize_name(deck_name)

    for sheet_idx, chunk in enumerate(chunks, start=1):
        num_cards = len(chunk)
        cols, rows = calculate_optimal_grid(num_cards, card_w, card_h)
        sheet_suffix = f"_{sheet_idx:02d}" if len(chunks) > 1 else ""

        front_tex_name = f"{clean_deck}{sheet_suffix}_front.png"
        back_tex_name = f"{clean_deck}{sheet_suffix}_back.png"

        front_tex_path = textures_dir / front_tex_name
        back_tex_path = textures_dir / back_tex_name

        atlas_f = Image.new("RGB", (cols * card_w, rows * card_h), (255, 255, 255))
        atlas_b = Image.new("RGB", (cols * card_w, rows * card_h), (255, 255, 255))

        for idx, (f_path, b_path) in enumerate(chunk):
            c = idx % cols
            r = idx // cols
            pos = (c * card_w, r * card_h)

            with Image.open(f_path) as im_f:
                atlas_f.paste(im_f, pos)
            with Image.open(b_path) as im_b:
                atlas_b.paste(im_b, pos)

        atlas_f.save(front_tex_path)
        atlas_b.save(back_tex_path)
        print(f"  [+] Generated sheet {cols}x{rows}: {front_tex_name}")

        card_guid = uuid.uuid4().hex.upper()
        template_name = f"{deck_name} (Sheet {sheet_idx})" if len(chunks) > 1 else deck_name
        indices = list(range(num_cards))

        template_data = build_card_template(
            guid=card_guid,
            name=template_name,
            front_tex=front_tex_name,
            back_tex=back_tex_name,
            cols=cols,
            rows=rows,
            indices=indices,
            is_guidebook=is_guidebook
        )

        template_file = templates_dir / f"{card_guid}Card.json"
        with open(template_file, "w", encoding="utf-8") as tf:
            json.dump(template_data, tf, indent=2)

def generate_manifest():
    manifest_path = package_dest / "Manifest.json"
    manifest_guid = uuid.uuid4().hex.upper()
    data = {
        "Name": package_name,
        "Version": "1",
        "GUID": manifest_guid
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[OK] Saved Manifest.json with GUID: {manifest_guid}")

def main():
    deck_dirs = find_deck_directories(output_root)
    if not deck_dirs:
        print(f"[FAIL-FAST] No decks found in {output_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Starting compilation of package '{package_name}'.")
    print(f"[*] Found {len(deck_dirs)} deck folders.")

    generate_manifest()

    for d in deck_dirs:
        process_deck(d)

    print(f"\n[SUCCESS] Package ready: {package_dest}")

if __name__ == "__main__":
    main()