"""
NiceGUI Desktop Management Interface for the TTPG Deck Pipeline.

Provides an interactive dashboard for pipeline execution (extraction, packaging, installation)
and a visual calibration tool for tuning PDF cut grids and duplex alignment.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Optional

# Pre-flight runtime dependency verification
REQUIRED_DEPENDENCIES: Final[dict[str, str]] = {
    "pymupdf": "pymupdf",
    "PIL": "pillow",
    "nicegui": "nicegui",
}

for module_name, pip_package in REQUIRED_DEPENDENCIES.items():
    try:
        __import__(module_name)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_package])

import pymupdf
from nicegui import app, ui

# ---------------------------------------------------------------------------
# Constants & Paths
# ---------------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
CONFIG_PATH: Final[Path] = BASE_DIR / "config.json"
LOCALES_DIR: Final[Path] = BASE_DIR / "locales"
TTPG_PACKAGES_DIR: Final[Path] = Path(
    os.path.expandvars(r"%LOCALAPPDATA%\TabletopPlayground\Packages")
)

PREVIEW_DPI: Final[int] = 100
PREVIEW_SCALE: Final[float] = PREVIEW_DPI / 72.0


# ---------------------------------------------------------------------------
# State & Configuration Management
# ---------------------------------------------------------------------------
@dataclass
class ApplicationState:
    current_lang: str = "en"
    is_busy: bool = False
    execution_logs: list[str] = field(default_factory=list)
    preview_dims: dict[str, float] = field(default_factory=lambda: {"w": 0.0, "h": 0.0})


class ConfigRepository:
    """Handles thread-safe reading and persistence of config.json."""

    @staticmethod
    def load() -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            print(f"[FAIL-FAST] Missing configuration at: {CONFIG_PATH}", file=sys.stderr)
            return {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:
            print(f"[FAIL-FAST] Failed to parse config.json: {exc}", file=sys.stderr)
            return {}

    @staticmethod
    def save(data: dict[str, Any]) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
        except Exception as exc:
            print(f"[ERROR] Failed to save config: {exc}", file=sys.stderr)


class LocaleManager:
    """Manages multi-language dictionaries with fallback resolution."""

    def __init__(self, locales_dir: Path) -> None:
        self.locales: dict[str, dict[str, str]] = {}
        if locales_dir.exists():
            for locale_file in locales_dir.glob("*.json"):
                try:
                    with open(locale_file, "r", encoding="utf-8") as file:
                        self.locales[locale_file.stem] = json.load(file)
                except Exception as exc:
                    print(f"[WARN] Failed to load locale {locale_file.name}: {exc}", file=sys.stderr)

    def translate(self, key: str, lang: str) -> str:
        return self.locales.get(lang, {}).get(key, self.locales.get("en", {}).get(key, key))


# Global Runtime Services
state = ApplicationState()
config_data = ConfigRepository.load()
locale_mgr = LocaleManager(LOCALES_DIR)


def t(key: str) -> str:
    return locale_mgr.translate(key, state.current_lang)


def open_system_folder(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))


def get_input_dir() -> Path:
    return BASE_DIR / config_data.get("dirs", {}).get("input", "_INPUT")


def get_pdf_candidates() -> list[Path]:
    in_dir = get_input_dir()
    if not in_dir.exists():
        return []
    return sorted(list(in_dir.rglob("*.pdf")))


# ---------------------------------------------------------------------------
# PDF Vector Inspection & Grid Heuristics
# ---------------------------------------------------------------------------
class PdfGridAnalyzer:
    """Analyzes vector cut marks and dimensions from PDF pages."""

    @staticmethod
    def detect_grid(pdf_path: Path) -> dict[str, Any]:
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        page = doc[0]
        page_w, page_h = round(page.rect.width, 1), round(page.rect.height, 1)

        is_doc = (
            total_pages <= 2
            or "guidebook" in pdf_path.name.lower()
            or "instruction" in pdf_path.name.lower()
            or "manual" in pdf_path.name.lower()
        )

        if is_doc:
            doc.close()
            return {
                "cols": 1,
                "rows": 1,
                "card_width_pt": page_w,
                "card_height_pt": page_h,
                "origin_x_pt": 0.0,
                "origin_y_pt": 0.0,
                "gutter_x_pt": 0.0,
                "gutter_y_pt": 0.0,
                "duplex_flip": "none",
                "matched_preset": "full_page_duplex",
            }

        drawings = page.get_drawings()
        marks = [d["rect"] for d in drawings if d["rect"].width < 4 or d["rect"].height < 4]
        doc.close()

        xs = sorted(list({round(r.x0, 1) for r in marks if r.width < 4 and 10 < r.x0 < (page_w - 10)}))
        ys = sorted(list({round(r.y0, 1) for r in marks if r.height < 4 and 10 < r.y0 < (page_h - 10)}))

        # Fallback to single page if crop marks are absent
        if len(xs) < 2 or len(ys) < 2:
            return {
                "cols": 1,
                "rows": 1,
                "card_width_pt": page_w,
                "card_height_pt": page_h,
                "origin_x_pt": 0.0,
                "origin_y_pt": 0.0,
                "gutter_x_pt": 0.0,
                "gutter_y_pt": 0.0,
                "duplex_flip": "none",
                "matched_preset": "full_page_duplex",
            }

        # Eco Layout (3x4 grid)
        if len(xs) >= 4 and len(ys) >= 5:
            return {
                "cols": 3,
                "rows": 4,
                "card_width_pt": 180.0,
                "card_height_pt": 180.0,
                "origin_x_pt": 36.0,
                "origin_y_pt": 36.0,
                "gutter_x_pt": 0.0,
                "gutter_y_pt": 0.0,
                "duplex_flip": "horizontal",
                "matched_preset": "story_engine_eco",
            }

        # Standard Layout (2x3 grid)
        return {
            "cols": 2,
            "rows": 3,
            "card_width_pt": 216.0,
            "card_height_pt": 216.0,
            "origin_x_pt": 80.95,
            "origin_y_pt": 54.0,
            "gutter_x_pt": 18.0,
            "gutter_y_pt": 18.0,
            "duplex_flip": "horizontal",
            "matched_preset": "story_engine_standard",
        }

    @staticmethod
    def render_page_base64(pdf_path: Path, page_num: int = 0) -> tuple[str, float, float]:
        doc = pymupdf.open(pdf_path)
        page = doc[page_num]
        matrix = pymupdf.Matrix(PREVIEW_SCALE, PREVIEW_SCALE)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        img_bytes = pixmap.tobytes("png")
        doc.close()

        b64_str = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64_str}", pixmap.width, pixmap.height


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
) -> str:
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
                f'fill="rgba(33, 150, 243, 0.2)" stroke="#1976d2" stroke-width="2" rx="3"/>'
                f'<text x="{x + 6:.1f}" y="{y + 18:.1f}" fill="#ffffff" font-size="13" '
                f'font-family="monospace" font-weight="bold" stroke="#000" stroke-width="0.5">#{card_index}</text>'
            )
            card_index += 1

    body = "".join(svg_elements)
    if img_w > 0 and img_h > 0:
        return f'<svg viewBox="0 0 {img_w:.1f} {img_h:.1f}" width="100%" height="100%">{body}</svg>'
    return body


# ---------------------------------------------------------------------------
# UI Construction
# ---------------------------------------------------------------------------
ui.colors(primary="#1976d2", secondary="#26a69a", accent="#9c27b0", dark="#121212")

lang_selector_ref: Optional[ui.select] = None

with ui.header().classes("items-center justify-between"):
    title_label = ui.label(t("app_title")).classes("text-h6 font-bold")
    with ui.row().classes("items-center gap-2"):
        btn_pdf = ui.button(
            t("btn_open_pdf_dir"),
            icon="folder",
            on_click=lambda: open_system_folder(get_input_dir()),
        ).props("flat color=white")

        btn_ttpg = ui.button(
            t("btn_open_ttpg_dir"),
            icon="gamepad",
            on_click=lambda: open_system_folder(TTPG_PACKAGES_DIR),
        ).props("flat color=white")

        def handle_language_change(event: Any) -> None:
            if state.is_busy:
                return
            state.current_lang = event.value
            title_label.text = t("app_title")
            btn_pdf.text = t("btn_open_pdf_dir")
            btn_ttpg.text = t("btn_open_ttpg_dir")
            render_dashboard.refresh()

        lang_selector_ref = ui.select(
            {"en": "English", "pl": "Polski"},
            value=state.current_lang,
            on_change=handle_language_change,
        ).props("dense borderless dark options-dark").classes("w-28 text-white")


@ui.refreshable
def render_dashboard() -> None:
    with ui.tabs().classes("w-full") as tabs:
        tab_pipeline = ui.tab(t("tab_pipeline"))
        tab_calibrator = ui.tab(t("tab_calibrator"))

    with ui.tab_panels(tabs, value=tab_pipeline).classes("w-full max-w-6xl mx-auto q-pa-md"):
        # -------------------------------------------------------------------
        # Panel 1: Execution Pipeline
        # -------------------------------------------------------------------
        with ui.tab_panel(tab_pipeline):
            with ui.stepper().props("vertical").classes("w-full") as stepper:
                # Step 1: Configuration
                with ui.step(t("step_1_title")):
                    ui.markdown(t("step_1_desc"))
                    with ui.grid(columns=2).classes("w-full"):
                        pkg_name_in = ui.input(
                            t("pkg_name_label"),
                            value=config_data.get("ttpg", {}).get("package_name", "The Story Engine Universe"),
                        ).classes("w-full")

                        dpi_in = ui.number(
                            t("dpi_label"),
                            value=config_data.get("dpi", 200),
                            format="%d",
                        ).classes("w-full")

                        in_dir_in = ui.input(
                            t("input_dir_label"),
                            value=config_data.get("dirs", {}).get("input", "_INPUT"),
                        ).classes("w-full")

                        out_dir_in = ui.input(
                            t("output_dir_label"),
                            value=config_data.get("dirs", {}).get("output", "_OUTPUT"),
                        ).classes("w-full")

                        pkg_dir_in = ui.input(
                            t("package_dir_label"),
                            value=config_data.get("ttpg", {}).get("output_dir", "_PACKAGE"),
                        ).classes("w-full")

                    def save_pipeline_settings() -> None:
                        config_data.setdefault("ttpg", {})["package_name"] = pkg_name_in.value
                        config_data.setdefault("ttpg", {})["output_dir"] = pkg_dir_in.value
                        config_data["dpi"] = int(dpi_in.value)
                        config_data.setdefault("dirs", {})["input"] = in_dir_in.value
                        config_data.setdefault("dirs", {})["output"] = out_dir_in.value
                        ConfigRepository.save(config_data)
                        ui.notify(t("notify_config_saved"), type="positive")
                        stepper.next()

                    with ui.stepper_navigation():
                        ui.button(t("btn_save_and_next"), on_click=save_pipeline_settings).props("icon-right=arrow_forward")

                # Step 2: Extraction
                with ui.step(t("step_2_title")):
                    ui.markdown(t("step_2_desc"))
                    log_extract = ui.log().classes("w-full h-44 bg-grey-10 text-white font-mono text-caption")
                    for line in state.execution_logs:
                        log_extract.push(line)

                    async def run_extraction() -> None:
                        if state.is_busy:
                            return
                        state.is_busy = True
                        if lang_selector_ref:
                            lang_selector_ref.disable()
                        btn_extract.disable()

                        state.execution_logs.clear()
                        log_extract.clear()

                        def log_output(msg: str) -> None:
                            state.execution_logs.append(msg)
                            log_extract.push(msg)

                        log_output("[START] Invoking deck_processor.py...")
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                sys.executable,
                                "-u",
                                str(BASE_DIR / "deck_processor.py"),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.STDOUT,
                            )
                            while raw_line := await proc.stdout.readline():
                                log_output(raw_line.decode("utf-8", errors="replace").rstrip())
                            await proc.wait()

                            if proc.returncode == 0:
                                ui.notify(t("notify_extract_ok"), type="positive")
                                stepper.next()
                            else:
                                ui.notify(t("notify_extract_fail"), type="negative")
                        finally:
                            state.is_busy = False
                            if lang_selector_ref:
                                lang_selector_ref.enable()
                            btn_extract.enable()

                    with ui.row():
                        btn_extract = ui.button(
                            t("btn_run_extract"),
                            icon="play_arrow",
                            on_click=run_extraction,
                        ).props("color=primary")

                        ui.button(
                            t("btn_open_output"),
                            icon="folder_open",
                            on_click=lambda: open_system_folder(BASE_DIR / out_dir_in.value),
                        ).props("outline")

                    with ui.stepper_navigation():
                        ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

                # Step 3: Packaging
                with ui.step(t("step_3_title")):
                    ui.markdown(t("step_3_desc"))
                    log_pack = ui.log().classes("w-full h-44 bg-grey-10 text-white font-mono text-caption")
                    for line in state.execution_logs:
                        log_pack.push(line)

                    async def run_packaging() -> None:
                        if state.is_busy:
                            return
                        state.is_busy = True
                        if lang_selector_ref:
                            lang_selector_ref.disable()
                        btn_pack.disable()

                        state.execution_logs.clear()
                        log_pack.clear()

                        def log_output(msg: str) -> None:
                            state.execution_logs.append(msg)
                            log_pack.push(msg)

                        log_output("[START] Invoking ttpg_packager.py...")
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                sys.executable,
                                "-u",
                                str(BASE_DIR / "ttpg_packager.py"),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.STDOUT,
                            )
                            while raw_line := await proc.stdout.readline():
                                log_output(raw_line.decode("utf-8", errors="replace").rstrip())
                            await proc.wait()

                            if proc.returncode == 0:
                                ui.notify(t("notify_package_ok"), type="positive")
                                stepper.next()
                            else:
                                ui.notify(t("notify_package_fail"), type="negative")
                        finally:
                            state.is_busy = False
                            if lang_selector_ref:
                                lang_selector_ref.enable()
                            btn_pack.enable()

                    with ui.row():
                        btn_pack = ui.button(
                            t("btn_run_package"),
                            icon="build",
                            on_click=run_packaging,
                        ).props("color=primary")

                        target_pkg_dir = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        ui.button(
                            t("btn_open_mod"),
                            icon="folder_open",
                            on_click=lambda: open_system_folder(target_pkg_dir),
                        ).props("outline")

                    with ui.stepper_navigation():
                        ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

                # Step 4: Installation
                with ui.step(t("step_4_title")):
                    ui.markdown(t("step_4_desc"))

                    def install_to_ttpg_environment() -> None:
                        source_pkg = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        if not source_pkg.exists():
                            ui.notify(t("notify_no_package"), type="warning")
                            return

                        target_dest = TTPG_PACKAGES_DIR / pkg_name_in.value
                        try:
                            TTPG_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
                            shutil.copytree(source_pkg, target_dest, dirs_exist_ok=True)
                            ui.notify(t("notify_install_ok"), type="positive")
                        except Exception as exc:
                            print(f"[FAIL-FAST] Installation failed: {exc}", file=sys.stderr)
                            ui.notify(f"{t('notify_install_fail')} ({exc})", type="negative")

                    with ui.row().classes("gap-3"):
                        ui.button(
                            t("btn_install_direct"),
                            icon="download_done",
                            on_click=install_to_ttpg_environment,
                        ).props("color=primary")

                        target_pkg_dir = BASE_DIR / pkg_dir_in.value / pkg_name_in.value
                        ui.button(
                            t("btn_open_target_pkg"),
                            icon="folder",
                            on_click=lambda: open_system_folder(target_pkg_dir),
                        ).props("outline")

                        ui.button(
                            t("btn_open_ttpg_pkgs"),
                            icon="gamepad",
                            on_click=lambda: open_system_folder(TTPG_PACKAGES_DIR),
                        ).props("flat")

        # -------------------------------------------------------------------
        # Panel 2: Visual Calibrator
        # -------------------------------------------------------------------
        with ui.tab_panel(tab_calibrator):
            ui.markdown(f"### {t('calibrator_title')}")
            ui.markdown(t("calibrator_desc"))

            candidates = get_pdf_candidates()
            in_root = get_input_dir()
            pdf_options = {str(p.relative_to(in_root)): p for p in candidates}

            with ui.row().classes("w-full items-center"):
                pdf_select = ui.select(
                    list(pdf_options.keys()),
                    label=t("select_pdf_label"),
                    value=list(pdf_options.keys())[0] if pdf_options else None,
                ).classes("w-96")

                auto_btn = ui.button(t("btn_auto_detect"), icon="auto_fix_high").props("color=secondary")

            with ui.row().classes("w-full items-start gap-6"):
                with ui.card().classes("w-96 q-pa-md"):
                    ui.label(t("card_params_box")).classes("text-subtitle2 font-bold")
                    presets = config_data.get("profiles", {})
                    preset_options = list(presets.keys())

                    def apply_preset(name: str) -> None:
                        if name not in presets:
                            return
                        profile = presets[name]
                        grid_def = profile.get("grid", {})
                        cols_in.value = grid_def.get("cols", 1)
                        rows_in.value = grid_def.get("rows", 1)
                        w_in.value = grid_def.get("card_width_pt", 216.0)
                        h_in.value = grid_def.get("card_height_pt", 216.0)
                        ox_in.value = grid_def.get("origin_x_pt", 0.0)
                        oy_in.value = grid_def.get("origin_y_pt", 0.0)
                        gx_in.value = grid_def.get("gutter_x_pt", 0.0)
                        gy_in.value = grid_def.get("gutter_y_pt", 0.0)
                        duplex_in.value = profile.get("duplex_flip", "horizontal")
                        refresh_overlay()

                    ui.select(
                        preset_options,
                        label="Load Preset",
                        on_change=lambda e: apply_preset(e.value),
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

                    def save_calibrated_profile() -> None:
                        p_name = profile_name_in.value.strip()
                        if not p_name:
                            ui.notify("Invalid profile name", type="negative")
                            return

                        is_single_doc = int(cols_in.value) == 1 and int(rows_in.value) == 1

                        # Clean profile schema without nulls
                        config_data.setdefault("profiles", {})[p_name] = {
                            "description": f"Calibrated for {pdf_select.value}",
                            "duplex_flip": duplex_in.value,
                            "model": "Square" if is_single_doc else "Rounded",
                            "thickness_cm": 0.03 if is_single_doc else 0.05,
                            "grid": {
                                "cols": int(cols_in.value),
                                "rows": int(rows_in.value),
                                "card_width_pt": float(w_in.value),
                                "card_height_pt": float(h_in.value),
                                "origin_x_pt": float(ox_in.value),
                                "origin_y_pt": float(oy_in.value),
                                "gutter_x_pt": float(gx_in.value),
                                "gutter_y_pt": float(gy_in.value),
                            },
                        }
                        ConfigRepository.save(config_data)
                        ui.notify(t("notify_profile_saved"), type="positive")

                    ui.button(
                        t("btn_save_profile"),
                        icon="save",
                        on_click=save_calibrated_profile,
                    ).props("color=primary").classes("w-full q-mt-md")

                with ui.card().classes("flex-1 q-pa-md items-center justify-center bg-grey-3"):
                    preview_image = ui.interactive_image().classes("shadow-4")

            def refresh_overlay() -> None:
                svg = generate_overlay_svg(
                    cols=int(cols_in.value or 1),
                    rows=int(rows_in.value or 1),
                    ox=float(ox_in.value or 0),
                    oy=float(oy_in.value or 0),
                    w=float(w_in.value or 0),
                    h=float(h_in.value or 0),
                    gx=float(gx_in.value or 0),
                    gy=float(gy_in.value or 0),
                    img_w=state.preview_dims["w"],
                    img_h=state.preview_dims["h"],
                )
                preview_image.content = svg

            def load_selected_pdf_preview() -> None:
                if not pdf_select.value:
                    return
                full_path = pdf_options[pdf_select.value]
                src, width, height = PdfGridAnalyzer.render_page_base64(full_path, 0)
                state.preview_dims["w"] = width
                state.preview_dims["h"] = height
                preview_image.set_source(src)
                refresh_overlay()

            def run_auto_detect() -> None:
                if not pdf_select.value:
                    return
                full_path = pdf_options[pdf_select.value]
                detection = PdfGridAnalyzer.detect_grid(full_path)

                cols_in.value = detection["cols"]
                rows_in.value = detection["rows"]
                w_in.value = detection["card_width_pt"]
                h_in.value = detection["card_height_pt"]
                ox_in.value = detection["origin_x_pt"]
                oy_in.value = detection["origin_y_pt"]
                gx_in.value = detection["gutter_x_pt"]
                gy_in.value = detection["gutter_y_pt"]
                duplex_in.value = detection["duplex_flip"]

                profile_name_in.value = f"profile_{full_path.stem[:14].lower().replace(' ', '_')}"
                refresh_overlay()
                ui.notify(t("notify_auto_detect_ok"), type="info")

            for widget in [cols_in, rows_in, w_in, h_in, ox_in, oy_in, gx_in, gy_in]:
                widget.on("update:model-value", refresh_overlay)

            pdf_select.on("update:model-value", load_selected_pdf_preview)
            auto_btn.on("click", run_auto_detect)

            ui.timer(0.1, load_selected_pdf_preview, once=True)


# ---------------------------------------------------------------------------
# Windows Proactor Socket Reset Suppression & App Runner
# ---------------------------------------------------------------------------
def patch_windows_proactor_loop() -> None:
    """Silences noisy WinError 10054 (ConnectionResetError) on Windows Proactor EventLoop."""
    if sys.platform == "win32":
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        original_handler = loop.get_exception_handler()

        def connection_reset_exception_handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            exc = context.get("exception")
            # Intercept and suppress abrupt client disconnects on Windows sockets
            if isinstance(exc, ConnectionResetError) or (isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10054):
                return
            if original_handler:
                original_handler(current_loop, context)
            else:
                current_loop.default_exception_handler(context)

        loop.set_exception_handler(connection_reset_exception_handler)


render_dashboard()
patch_windows_proactor_loop()

# Bind explicitly to localhost (127.0.0.1) to avoid binding to dead link-local 169.254.x.x interfaces
ui.run(
    host="127.0.0.1",
    port=8080,
    title="TTPG Deck Pipeline Manager",
    native=False,
    reload=False,
)