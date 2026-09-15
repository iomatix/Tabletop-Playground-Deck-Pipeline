import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REQUIRED_LIBS = {"pymupdf": "pymupdf", "PIL": "pillow", "nicegui": "nicegui"}
for mod, pip_pkg in REQUIRED_LIBS.items():
    try:
        __import__(mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_pkg])

import pymupdf
from nicegui import app, run, ui

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOCALES_DIR = BASE_DIR / "locales"
TTPG_PACKAGES_DIR = Path(os.path.expandvars(r"%LOCALAPPDATA%\TabletopPlayground\Packages"))

PREVIEW_DPI = 100
SCALE = PREVIEW_DPI / 72.0

LOCALES = {}
current_lang = "en"

# Globalny bufor i wskaźniki stanu
execution_logs = []
is_busy = False
lang_selector_widget = None


def load_all_locales():
    global LOCALES
    if LOCALES_DIR.exists():
        for f in LOCALES_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as jf:
                    LOCALES[f.stem] = json.load(jf)
            except Exception as e:
                print(f"[FAIL-FAST] Failed to load locale {f}: {e}", file=sys.stderr)


load_all_locales()


def t(key: str) -> str:
    return LOCALES.get(current_lang, {}).get(key, LOCALES.get("en", {}).get(key, key))


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[FAIL-FAST] Configuration file not found at {CONFIG_PATH}", file=sys.stderr)
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def open_folder(path: Path):
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))


config_data = load_config()


def get_input_dir() -> Path:
    return BASE_DIR / config_data.get("dirs", {}).get("input", "_INPUT")


def get_pdf_candidates() -> list[Path]:
    in_dir = get_input_dir()
    if not in_dir.exists():
        return []
    return sorted(list(in_dir.rglob("*.pdf")))


def detect_grid_from_pdf(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    page = doc[0]
    p_w, p_h = round(page.rect.width, 1), round(page.rect.height, 1)

    # Guidebook/Instruction/Manual detection based on filename or page count
    is_doc = (
        total_pages <= 2
        or "guidebook" in pdf_path.name.lower()
        or "instruction" in pdf_path.name.lower()
        or "manual" in pdf_path.name.lower()
    )
    if is_doc:
        doc.close()
        return {
            "cols": 1, "rows": 1,
            "card_width_pt": p_w, "card_height_pt": p_h,
            "origin_x_pt": 0.0, "origin_y_pt": 0.0,
            "gutter_x_pt": 0.0, "gutter_y_pt": 0.0,
            "duplex_flip": "none",
            "matched_preset": "full_page_duplex"
        }

    drawings = page.get_drawings()
    marks = [d["rect"] for d in drawings if d["rect"].width < 4 or d["rect"].height < 4]
    doc.close()

    xs = sorted(list({round(r.x0, 1) for r in marks if r.width < 4 and 10 < r.x0 < (p_w - 10)}))
    ys = sorted(list({round(r.y0, 1) for r in marks if r.height < 4 and 10 < r.y0 < (p_h - 10)}))

    # Book/Sheet/Instruction -> Full Page (1x1) if no valid cut marks detected
    if len(xs) < 2 or len(ys) < 2:
        return {
            "cols": 1, "rows": 1,
            "card_width_pt": p_w, "card_height_pt": p_h,
            "origin_x_pt": 0.0, "origin_y_pt": 0.0,
            "gutter_x_pt": 0.0, "gutter_y_pt": 0.0,
            "duplex_flip": "none",
            "matched_preset": "full_page_duplex"
        }

    # Eco (3x4)
    if len(xs) >= 4 and len(ys) >= 5:
        return {
            "cols": 3, "rows": 4,
            "card_width_pt": 180.0, "card_height_pt": 180.0,
            "origin_x_pt": 36.0, "origin_y_pt": 36.0,
            "gutter_x_pt": 0.0, "gutter_y_pt": 0.0,
            "duplex_flip": "horizontal",
            "matched_preset": "story_engine_eco"
        }

    # Standard (2x3)
    return {
        "cols": 2, "rows": 3,
        "card_width_pt": 216.0, "card_height_pt": 216.0,
        "origin_x_pt": 80.95, "origin_y_pt": 54.0,
        "gutter_x_pt": 18.0, "gutter_y_pt": 18.0,
        "duplex_flip": "horizontal",
        "matched_preset": "story_engine_standard"
    }

def render_pdf_page_base64(pdf_path: Path, page_num: int = 0) -> tuple[str, float, float]:
    doc = pymupdf.open(pdf_path)
    page = doc[page_num]
    mat = pymupdf.Matrix(SCALE, SCALE)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}", pix.width, pix.height


def generate_overlay_svg(cols: int, rows: int, ox: float, oy: float, w: float, h: float, gx: float, gy: float, img_w: float = 0, img_h: float = 0) -> str:
    svg_nodes = []
    card_idx = 1
    for r in range(rows):
        for c in range(cols):
            x = (ox + c * (w + gx)) * SCALE
            y = (oy + r * (h + gy)) * SCALE
            box_w = w * SCALE
            box_h = h * SCALE

            svg_nodes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" '
                f'fill="rgba(33, 150, 243, 0.2)" stroke="#1976d2" stroke-width="2" rx="3"/>'
                f'<text x="{x + 6:.1f}" y="{y + 18:.1f}" fill="#ffffff" font-size="13" '
                f'font-family="monospace" font-weight="bold" stroke="#000" stroke-width="0.5">#{card_idx}</text>'
            )
            card_idx += 1

    content = "".join(svg_nodes)
    if img_w > 0 and img_h > 0:
        return f'<svg viewBox="0 0 {img_w:.1f} {img_h:.1f}" width="100%" height="100%">{content}</svg>'
    return content


ui.colors(primary="#1976d2", secondary="#26a69a", accent="#9c27b0", dark="#121212")

with ui.header().classes("items-center justify-between"):
    title_label = ui.label(t("app_title")).classes("text-h6 font-bold")
    with ui.row().classes("items-center gap-2"):
        btn_pdf = ui.button(t("btn_open_pdf_dir"), icon="folder", on_click=lambda: open_folder(get_input_dir())).props("flat color=white")
        btn_ttpg = ui.button(t("btn_open_ttpg_dir"), icon="gamepad", on_click=lambda: open_folder(TTPG_PACKAGES_DIR)).props("flat color=white")

        def change_language(e):
            global current_lang
            if is_busy:
                return
            current_lang = e.value
            title_label.text = t("app_title")
            btn_pdf.text = t("btn_open_pdf_dir")
            btn_ttpg.text = t("btn_open_ttpg_dir")
            render_main_interface.refresh()

        lang_selector_widget = ui.select(
            {"en": "English", "pl": "Polski"},
            value=current_lang,
            on_change=change_language
        ).props("dense borderless dark options-dark").classes("w-28 text-white")


@ui.refreshable
def render_main_interface():
    with ui.tabs().classes("w-full") as tabs:
        tab_pipeline = ui.tab(t("tab_pipeline"))
        tab_calibrator = ui.tab(t("tab_calibrator"))

    with ui.tab_panels(tabs, value=tab_pipeline).classes("w-full max-w-6xl mx-auto q-pa-md"):
        # PANEL 1: PIPELINE
        with ui.tab_panel(tab_pipeline):
            with ui.stepper().props("vertical").classes("w-full") as stepper:
                # Step 1: Configuration
                with ui.step(t("step_1_title")):
                    ui.markdown(t("step_1_desc"))
                    with ui.grid(columns=2).classes("w-full"):
                        pkg_name_in = ui.input(t("pkg_name_label"), value=config_data.get("ttpg", {}).get("package_name", "The Story Engine Universe")).classes("w-full")
                        dpi_in = ui.number(t("dpi_label"), value=config_data.get("dpi", 200), format="%d").classes("w-full")
                        in_dir_in = ui.input(t("input_dir_label"), value=config_data.get("dirs", {}).get("input", "_INPUT")).classes("w-full")
                        out_dir_in = ui.input(t("output_dir_label"), value=config_data.get("dirs", {}).get("output", "_OUTPUT")).classes("w-full")
                        pkg_dir_in = ui.input(t("package_dir_label"), value=config_data.get("ttpg", {}).get("output_dir", "_PACKAGE")).classes("w-full")

                    def save_settings():
                        config_data.setdefault("ttpg", {})["package_name"] = pkg_name_in.value
                        config_data.setdefault("ttpg", {})["output_dir"] = pkg_dir_in.value
                        config_data["dpi"] = int(dpi_in.value)
                        config_data.setdefault("dirs", {})["input"] = in_dir_in.value
                        config_data.setdefault("dirs", {})["output"] = out_dir_in.value
                        save_config(config_data)
                        ui.notify(t("notify_config_saved"), type="positive")
                        stepper.next()

                    with ui.stepper_navigation():
                        ui.button(t("btn_save_and_next"), on_click=save_settings).props("icon-right=arrow_forward")

                # Step 2: Extraction
                with ui.step(t("step_2_title")):
                    ui.markdown(t("step_2_desc"))
                    log_extract = ui.log().classes("w-full h-44 bg-grey-10 text-white font-mono text-caption")
                    for entry in execution_logs:
                        log_extract.push(entry)

                    async def run_extraction():
                        global is_busy
                        if is_busy:
                            return

                        is_busy = True
                        if lang_selector_widget:
                            lang_selector_widget.disable()
                        btn_extract.disable()

                        execution_logs.clear()
                        log_extract.clear()

                        def append_log(line: str):
                            execution_logs.append(line)
                            log_extract.push(line)

                        append_log("[START] Running deck_processor.py...")
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                sys.executable, "-u", str(BASE_DIR / "deck_processor.py"),
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
                            )
                            while line := await proc.stdout.readline():
                                append_log(line.decode("utf-8", errors="replace").rstrip())
                            await proc.wait()

                            if proc.returncode == 0:
                                ui.notify(t("notify_extract_ok"), type="positive")
                                stepper.next()
                            else:
                                ui.notify(t("notify_extract_fail"), type="negative")
                        finally:
                            is_busy = False
                            if lang_selector_widget:
                                lang_selector_widget.enable()
                            btn_extract.enable()

                    with ui.row():
                        btn_extract = ui.button(t("btn_run_extract"), icon="play_arrow", on_click=run_extraction).props("color=primary")
                        ui.button(t("btn_open_output"), icon="folder_open", on_click=lambda: open_folder(BASE_DIR / out_dir_in.value)).props("outline")

                    with ui.stepper_navigation():
                        ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

                # Step 3: Packaging
                with ui.step(t("step_3_title")):
                    ui.markdown(t("step_3_desc"))
                    log_pack = ui.log().classes("w-full h-44 bg-grey-10 text-white font-mono text-caption")
                    for entry in execution_logs:
                        log_pack.push(entry)

                    async def run_packaging():
                        global is_busy
                        if is_busy:
                            return

                        is_busy = True
                        if lang_selector_widget:
                            lang_selector_widget.disable()
                        btn_pack.disable()

                        execution_logs.clear()
                        log_pack.clear()

                        def append_log(line: str):
                            execution_logs.append(line)
                            log_pack.push(line)

                        append_log("[START] Running ttpg_packager.py...")
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                sys.executable, "-u", str(BASE_DIR / "ttpg_packager.py"),
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
                            )
                            while line := await proc.stdout.readline():
                                append_log(line.decode("utf-8", errors="replace").rstrip())
                            await proc.wait()

                            if proc.returncode == 0:
                                ui.notify(t("notify_package_ok"), type="positive")
                                stepper.next()
                            else:
                                ui.notify(t("notify_package_fail"), type="negative")
                        finally:
                            is_busy = False
                            if lang_selector_widget:
                                lang_selector_widget.enable()
                            btn_pack.enable()

                    with ui.row():
                        btn_pack = ui.button(t("btn_run_package"), icon="build", on_click=run_packaging).props("color=primary")
                        target_pkg = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        ui.button(t("btn_open_mod"), icon="folder_open", on_click=lambda: open_folder(target_pkg)).props("outline")

                    with ui.stepper_navigation():
                        ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

                # Step 4: Installation
                with ui.step(t("step_4_title")):
                    ui.markdown(t("step_4_desc"))

                    def install_package_to_ttpg():
                        source_pkg = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        if not source_pkg.exists():
                            ui.notify(t("notify_no_package"), type="warning")
                            return

                        target_destination = TTPG_PACKAGES_DIR / pkg_name_in.value
                        try:
                            TTPG_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
                            shutil.copytree(source_pkg, target_destination, dirs_exist_ok=True)
                            ui.notify(t("notify_install_ok"), type="positive")
                        except Exception as ex:
                            print(f"[FAIL-FAST] Installation failed: {ex}", file=sys.stderr)
                            ui.notify(f"{t('notify_install_fail')} ({ex})", type="negative")

                    with ui.row().classes("gap-3"):
                        ui.button(t("btn_install_direct"), icon="download_done", on_click=install_package_to_ttpg).props("color=primary")
                        target_pkg = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        ui.button(t("btn_open_target_pkg"), icon="folder", on_click=lambda: open_folder(target_pkg)).props("outline")
                        ui.button(t("btn_open_ttpg_pkgs"), icon="gamepad", on_click=lambda: open_folder(TTPG_PACKAGES_DIR)).props("flat")

        # PANEL 2: CALIBRATOR
        with ui.tab_panel(tab_calibrator):
            ui.markdown(f"### {t('calibrator_title')}")
            ui.markdown(t("calibrator_desc"))

            candidates = get_pdf_candidates()
            in_dir = get_input_dir()
            pdf_options = {str(p.relative_to(in_dir)): p for p in candidates}

            with ui.row().classes("w-full items-center"):
                pdf_select = ui.select(
                    list(pdf_options.keys()),
                    label=t("select_pdf_label"),
                    value=list(pdf_options.keys())[0] if pdf_options else None
                ).classes("w-96")
                auto_btn = ui.button(t("btn_auto_detect"), icon="auto_fix_high").props("color=secondary")

            with ui.row().classes("w-full items-start gap-6"):
                with ui.card().classes("w-96 q-pa-md"):
                    ui.label(t("card_params_box")).classes("text-subtitle2 font-bold")
                    presets = config_data.get("profiles", {})
                    preset_options = list(presets.keys())

                    def apply_preset(preset_name):
                        if preset_name not in presets:
                            return
                        p = presets[preset_name]
                        g = p.get("grid", {})
                        cols_in.value = g.get("cols", 1)
                        rows_in.value = g.get("rows", 1)
                        w_in.value = g.get("card_width_pt", 216.0)
                        h_in.value = g.get("card_height_pt", 216.0)
                        ox_in.value = g.get("origin_x_pt", 0.0)
                        oy_in.value = g.get("origin_y_pt", 0.0)
                        gx_in.value = g.get("gutter_x_pt", 0.0)
                        gy_in.value = g.get("gutter_y_pt", 0.0)
                        duplex_in.value = p.get("duplex_flip", "horizontal")
                        refresh_overlay()

                    ui.select(
                        preset_options,
                        label="Load Preset",
                        on_change=lambda e: apply_preset(e.value)
                    ).classes("w-full q-mb-sm")

                    profile_name_in = ui.input(t("profile_name_label"), value="custom_profile")
                    cols_in = ui.number(t("cols_label"), value=2, min=1, max=10, format="%d")
                    rows_in = ui.number(t("rows_label"), value=3, min=1, max=10, format="%d")

                    w_in = ui.number(t("card_w_label"), value=216.0, step=0.5, format="%.2f")
                    h_in = ui.number(t("card_h_label"), value=216.0, step=0.5, format="%.2f")

                    ox_in = ui.number(t("origin_x_label"), value=80.95, step=0.5, format="%.2f")
                    oy_in = ui.number(t("origin_y_label"), value=54.0, step=0.5, format="%.2f")

                    gx_in = ui.number(t("gutter_x_label"), value=18.0, step=0.5, format="%.2f")
                    gy_in = ui.number(t("gutter_y_label"), value=18.0, step=0.5, format="%.2f")

                    duplex_in = ui.select(["horizontal", "vertical", "none"], value="horizontal", label=t("duplex_label"))

                    def save_calibrated_profile():
                        p_name = profile_name_in.value.strip()
                        if not p_name:
                            ui.notify("Invalid profile name!", type="negative")
                            return

                        config_data.setdefault("profiles", {})[p_name] = {
                            "description": f"Calibrated for {pdf_select.value}",
                            "duplex_flip": duplex_in.value,
                            "grid": {
                                "cols": int(cols_in.value),
                                "rows": int(rows_in.value),
                                "card_width_pt": float(w_in.value),
                                "card_height_pt": float(h_in.value),
                                "origin_x_pt": float(ox_in.value),
                                "origin_y_pt": float(oy_in.value),
                                "gutter_x_pt": float(gx_in.value),
                                "gutter_y_pt": float(gy_in.value)
                            }
                        }
                        save_config(config_data)
                        ui.notify(t("notify_profile_saved"), type="positive")

                    ui.button(t("btn_save_profile"), icon="save", on_click=save_calibrated_profile).props("color=primary").classes("w-full q-mt-md")

                with ui.card().classes("flex-1 q-pa-md items-center justify-center bg-grey-3"):
                    preview_image = ui.interactive_image().classes("shadow-4")

            # Izolowany stan wymiarów podglądu w obrębie panelu kalibratora
            preview_dim = {"w": 0.0, "h": 0.0}

            def refresh_overlay():
                svg = generate_overlay_svg(
                    cols=int(cols_in.value or 1),
                    rows=int(rows_in.value or 1),
                    ox=float(ox_in.value or 0),
                    oy=float(oy_in.value or 0),
                    w=float(w_in.value or 0),
                    h=float(h_in.value or 0),
                    gx=float(gx_in.value or 0),
                    gy=float(gy_in.value or 0),
                    img_w=preview_dim["w"],
                    img_h=preview_dim["h"]
                )
                preview_image.content = svg

            def load_selected_pdf_preview():
                if not pdf_select.value:
                    return
                full_path = pdf_options[pdf_select.value]
                src, w, h = render_pdf_page_base64(full_path, 0)
                preview_dim["w"] = w
                preview_dim["h"] = h
                preview_image.set_source(src)
                refresh_overlay()

            def run_auto_detect():
                if not pdf_select.value:
                    return
                full_path = pdf_options[pdf_select.value]
                det = detect_grid_from_pdf(full_path)

                cols_in.value = det["cols"]
                rows_in.value = det["rows"]
                w_in.value = det["card_width_pt"]
                h_in.value = det["card_height_pt"]
                ox_in.value = det["origin_x_pt"]
                oy_in.value = det["origin_y_pt"]
                gx_in.value = det["gutter_x_pt"]
                gy_in.value = det["gutter_y_pt"]
                duplex_in.value = det["duplex_flip"]

                profile_name_in.value = f"profile_{full_path.stem[:14].lower().replace(' ', '_')}"
                refresh_overlay()
                ui.notify(t("notify_auto_detect_ok"), type="info")

            for widget in [cols_in, rows_in, w_in, h_in, ox_in, oy_in, gx_in, gy_in]:
                widget.on("update:model-value", refresh_overlay)

            pdf_select.on("update:model-value", load_selected_pdf_preview)
            auto_btn.on("click", run_auto_detect)

            ui.timer(0.1, load_selected_pdf_preview, once=True)


render_main_interface()
ui.run(title="TTPG Deck Pipeline Manager", native=False, port=8080, reload=False)