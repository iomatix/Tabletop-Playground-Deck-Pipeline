import json
import sys
from pathlib import Path
import pymupdf
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

if not CONFIG_PATH.exists():
    print(f"[FAIL-FAST] Missing configuration file: {CONFIG_PATH}", file=sys.stderr)
    sys.exit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

profile_key = cfg.get("default_profile") or cfg.get("active_profile")
if profile_key not in cfg.get("profiles", {}):
    print(f"[FAIL-FAST] Profile '{profile_key}' does not exist in 'profiles'.", file=sys.stderr)
    sys.exit(1)

active_profile = cfg["profiles"][profile_key]
grid = active_profile["grid"]
dpi = cfg.get("dpi", 200)
zoom = dpi / 72.0

diag_dir = BASE_DIR / cfg.get("dirs", {}).get("diagnostics", "_DIAGNOSTICS")
diag_dir.mkdir(parents=True, exist_ok=True)

# Fetch mask: rules -> file_pattern -> default fallback
rules = cfg.get("rules", [])
pattern = rules[0].get("pattern", "*_HQ Cards.pdf") if rules else cfg.get("file_pattern", "*_HQ Cards.pdf")

candidates = sorted(list(BASE_DIR.rglob(pattern)))
if not candidates:
    print(f"[FAIL-FAST] No files matching pattern '{pattern}'.", file=sys.stderr)
    sys.exit(1)

sample_pdf = candidates[0]
doc = pymupdf.open(sample_pdf)
if len(doc) < 2:
    print(f"[FAIL-FAST] Document {sample_pdf.name} has fewer than 2 pages.", file=sys.stderr)
    sys.exit(1)

mat = pymupdf.Matrix(zoom, zoom)
pix_front = doc[0].get_pixmap(matrix=mat, alpha=False)
pix_back = doc[1].get_pixmap(matrix=mat, alpha=False)

img_f = Image.frombytes("RGB", [pix_front.width, pix_front.height], pix_front.samples)
img_b = Image.frombytes("RGB", [pix_back.width, pix_back.height], pix_back.samples)

def get_crop_box(col: int, row: int) -> tuple[int, int, int, int]:
    x0 = (grid["origin_x_pt"] + col * (grid["card_width_pt"] + grid["gutter_x_pt"])) * zoom
    y0 = (grid["origin_y_pt"] + row * (grid["card_height_pt"] + grid["gutter_y_pt"])) * zoom
    w = grid["card_width_pt"] * zoom
    h = grid["card_height_pt"] * zoom
    return (int(round(x0)), int(round(y0)), int(round(x0 + w)), int(round(y0 + h)))

crop_front = get_crop_box(col=0, row=0)
crop_back = get_crop_box(col=1, row=0)

card_f = img_f.crop(crop_front)
card_b = img_b.crop(crop_back)

out_f = diag_dir / "precise_card_000_front.png"
out_b = diag_dir / "precise_card_000_back.png"

card_f.save(out_f)
card_b.save(out_b)

print(f"[OK] Sample extracted from file: {sample_pdf.relative_to(BASE_DIR)}")
print(f"[OK] Front:  {out_f.relative_to(BASE_DIR)} {card_f.size}")
print(f"[OK] Back:   {out_b.relative_to(BASE_DIR)} {card_b.size}")
