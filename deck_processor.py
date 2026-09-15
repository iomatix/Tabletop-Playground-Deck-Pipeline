import hashlib
import json
import re
import sys
from pathlib import Path
import pymupdf

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_PATH = BASE_DIR / ".build_cache.json"

if not CONFIG_PATH.exists():
    print(f"[FAIL-FAST] Missing configuration file: {CONFIG_PATH}", file=sys.stderr)
    sys.exit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

input_root = BASE_DIR / cfg.get("dirs", {}).get("input", "_INPUT")
output_root = BASE_DIR / cfg.get("dirs", {}).get("output", "_OUTPUT")

if not input_root.exists():
    print(f"[FAIL-FAST] Input directory does not exist: {input_root}", file=sys.stderr)
    sys.exit(1)

dpi = cfg.get("dpi", 200)
scale = dpi / 72.0
matrix = pymupdf.Matrix(scale, scale)

build_cache = {}
if CACHE_PATH.exists():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as cf:
            build_cache = json.load(cf)
    except Exception:
        build_cache = {}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def resolve_profile_for_pdf(pdf_path: Path) -> tuple[dict | None, str | None]:
    local_conf = pdf_path.parent / "deck.json"
    effective_rule_profile = None

    for rule in cfg.get("rules", []):
        pattern = rule.get("pattern", "")
        if pdf_path.match(pattern) or Path(pdf_path.name).match(pattern):
            effective_rule_profile = rule.get("profile")
            break

    # Brak reguły i brak lokalnego configu = plik NIE jest przeznaczony do batcha
    if not effective_rule_profile and not local_conf.exists():
        return None, None

    profile_name = effective_rule_profile or cfg.get("default_profile")
    base_prof = cfg.get("profiles", {}).get(profile_name)

    if not base_prof:
        return None, None

    prof = json.loads(json.dumps(base_prof))

    if local_conf.exists():
        try:
            with open(local_conf, "r", encoding="utf-8") as lf:
                loc = json.load(lf)
            if "duplex_flip" in loc:
                prof["duplex_flip"] = loc["duplex_flip"]
            if "grid_overrides" in loc:
                prof["grid"].update(loc["grid_overrides"])
        except Exception as e:
            print(f"[WARN] Failed to parse local deck.json in {pdf_path.parent}: {e}", file=sys.stderr)

    return prof, profile_name

def process_pdf(pdf_path: Path):
    prof, prof_name = resolve_profile_for_pdf(pdf_path)
    if not prof:
        print(f"[IGNORE] No matching rule/profile for: {pdf_path.name}")
        return
    grid = prof["grid"]
    duplex_flip = prof.get("duplex_flip", "horizontal")

    current_hash = file_sha256(pdf_path)
    config_state_str = json.dumps({"hash": current_hash, "prof": prof, "dpi": dpi}, sort_keys=True)
    cache_key = str(pdf_path.relative_to(input_root))

    target_rel = pdf_path.parent.relative_to(input_root)
    clean_stem = pdf_path.stem
    for rule in cfg.get("rules", []):
        suffix = rule.get("strip_suffix")
        if suffix and clean_stem.endswith(suffix):
            clean_stem = clean_stem[:-len(suffix)].rstrip(" _-")
            break

    deck_out_dir = output_root / target_rel / clean_stem
    deck_out_dir.mkdir(parents=True, exist_ok=True)

    if build_cache.get(cache_key) == config_state_str and any(deck_out_dir.glob("card_*_front.png")):
        print(f"[SKIP] {pdf_path.name} (cached)")
        return

    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)

    # 1. Self-healing for single-page standalone documents (sheets/instructions)
    if total_pages == 1:
        prof = cfg.get("profiles", {}).get("full_page_duplex", prof)
        prof_name = "full_page_duplex (auto-detected single page)"
        grid = prof["grid"]
        duplex_flip = "none"

    # 2. Resilient classification: documents vs multi-card duplex decks
    is_guidebook = (
        total_pages == 1
        or "guidebook" in pdf_path.name.lower()
        or "instruction" in pdf_path.name.lower()
        or prof_name.startswith("full_page")
        or (grid["cols"] == 1 and grid["rows"] == 1)
    )

    # 3. Strict Fail-Fast applied ONLY to true multi-card decks
    if not is_guidebook and total_pages % 2 != 0:
        print(
            f"[FAIL-FAST] Odd page count ({total_pages}) detected in double-sided card deck: {pdf_path.name}\n"
            f"            If this is a rulebook or single sheet, add a rule to config.json or use 'full_page_duplex'.",
            file=sys.stderr
        )
        doc.close()
        sys.exit(1)

    print(f"\n[PROCESS] Extracting: {pdf_path.name} -> Profile: {prof_name}")

    cols = grid["cols"]
    rows = grid["rows"]
    w = grid["card_width_pt"]
    h = grid["card_height_pt"]
    ox = grid["origin_x_pt"]
    oy = grid["origin_y_pt"]
    gx = grid.get("gutter_x_pt", 0.0)
    gy = grid.get("gutter_y_pt", 0.0)

    card_counter = 1
    sheet_pairs = (total_pages + 1) // 2

    for pair_idx in range(sheet_pairs):
        f_idx = pair_idx * 2
        b_idx = f_idx + 1

        f_page = doc[f_idx]
        b_page = doc[b_idx] if b_idx < total_pages else None

        for r in range(rows):
            for c in range(cols):
                # Dynamiczna orientacja (Landscape/Portrait) dla pełnych stron/guidebooków
                if is_guidebook or (cols == 1 and rows == 1):
                    f_clip = f_page.rect
                    b_clip = b_page.rect if b_page else f_page.rect
                else:
                    fx0 = ox + c * (w + gx)
                    fy0 = oy + r * (h + gy)
                    f_clip = pymupdf.Rect(fx0, fy0, fx0 + w, fy0 + h)

                    if duplex_flip == "horizontal":
                        bc = cols - 1 - c
                        br = r
                    elif duplex_flip == "vertical":
                        bc = c
                        br = rows - 1 - r
                    else:
                        bc = c
                        br = r

                    bx0 = ox + bc * (w + gx)
                    by0 = oy + br * (h + gy)
                    b_clip = pymupdf.Rect(bx0, by0, bx0 + w, by0 + h)

                # Front side
                f_pix = f_page.get_pixmap(matrix=matrix, clip=f_clip, alpha=False)
                f_pix.save(deck_out_dir / f"card_{card_counter:03d}_front.png")

                # Back side (with blank fallback for odd trailing page)
                if b_page:
                    b_pix = b_page.get_pixmap(matrix=matrix, clip=b_clip, alpha=False)
                    b_pix.save(deck_out_dir / f"card_{card_counter:03d}_back.png")
                else:
                    cur_w = f_clip.width if (is_guidebook or (cols == 1 and rows == 1)) else w
                    cur_h = f_clip.height if (is_guidebook or (cols == 1 and rows == 1)) else h
                    blank = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, int(cur_w * scale), int(cur_h * scale)))
                    blank.clear_with(255)
                    blank.save(deck_out_dir / f"card_{card_counter:03d}_back.png")

                card_counter += 1

    doc.close()
    build_cache[cache_key] = config_state_str
    print(f"  [+] Saved {card_counter - 1} cards into: {deck_out_dir}")

def main():
    pdf_files = sorted(list(input_root.rglob("*.pdf")))
    if not pdf_files:
        print(f"[INFO] No PDF files found in {input_root}")
        return

    print(f"[*] Starting extraction from {input_root}. Discovered {len(pdf_files)} PDF file(s).")
    output_root.mkdir(parents=True, exist_ok=True)

    for pdf in pdf_files:
        process_pdf(pdf)

    with open(CACHE_PATH, "w", encoding="utf-8") as cf:
        json.dump(build_cache, cf, indent=2)
    print("\n[OK] Card extraction completed successfully.")


if __name__ == "__main__":
    main()