"""
Visual Grid Calibrator View.

Includes 2-Click Box Calibration, throttled 25-FPS SVG rendering pipeline,
and conflict-free keyboard controls (Ctrl+Arrows for Origin, Alt+Arrows for Gutters).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from nicegui import events, ui

from app.pdf_analyzer import PdfGridAnalyzer, generate_overlay_svg
from app.state import (
    PREVIEW_SCALE,
    ConfigRepository,
    config_data,
    get_input_dir,
    get_pdf_candidates,
    state,
    t,
)


def create_calibrator_view() -> None:
    ui.markdown(f"### {t('calibrator_title')}")
    ui.markdown(t("calibrator_desc"))

    candidates = get_pdf_candidates()
    in_root = get_input_dir()
    pdf_options = {str(p.relative_to(in_root)): p for p in candidates}

    two_click_mode: bool = False
    calibration_target: str = "card"
    first_click_point: Optional[tuple[float, float]] = None
    last_click_timestamp: float = 0.0

    # Throttle control state
    _is_refreshing: bool = False
    _needs_refresh: bool = False

    def reset_two_click_state() -> None:
        nonlocal two_click_mode, first_click_point
        two_click_mode = False
        first_click_point = None
        btn_two_click.props("outline color=primary")
        btn_two_click.text = t("btn_two_click")
        trigger_overlay_refresh()

    # Top Selection Row
    with ui.row().classes("w-full items-center justify-between q-mb-sm"):
        with ui.row().classes("items-center gap-3"):
            pdf_select = ui.select(
                list(pdf_options.keys()),
                label=t("select_pdf_label"),
                value=list(pdf_options.keys())[0] if pdf_options else None,
            ).classes("w-80")

            auto_btn = ui.button(t("btn_auto_detect"), icon="auto_fix_high").props("color=secondary")

        btn_two_click = ui.button(t("btn_two_click"), icon="crop").props("outline color=primary")

    # Main Row Container
    with ui.row().classes("w-full items-start gap-6"):
        # 1. Left Card: Parameters
        with ui.card().classes("w-96 q-pa-md"):
            with ui.row().classes("w-full items-center justify-between q-mb-xs"):
                ui.label(t("card_params_box")).classes("text-subtitle2 font-bold")
                btn_shortcuts_help = ui.button(icon="help_outline").props("flat round dense size=sm color=grey-7")

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
                trigger_overlay_refresh()

            ui.select(
                preset_options,
                label=t("load_preset_label"),
                on_change=lambda e: apply_preset(e.value),
            ).classes("w-full q-mb-sm")

            profile_name_in = ui.input(t("profile_name_label"), value="custom_profile")
            cols_in = ui.number(t("cols_label"), value=2, min=1, max=10, format="%d")
            rows_in = ui.number(t("rows_label"), value=3, min=1, max=10, format="%d")
            w_in = ui.number(t("card_w_label"), value=216.0, step=0.5, format="%.2f")
            h_in = ui.number(t("card_h_label"), value=216.0, step=0.5, format="%.2f")
            ox_in = ui.number(t("origin_x_label"), value=80.95, step=0.5, format="%.2f")
            oy_in = ui.number(t("origin_y_label"), value=54.0, step=0.5, format="%.2f")
            gx_in = ui.number(t("gutter_x_label"), value=0.0, step=0.5, format="%.2f")
            gy_in = ui.number(t("gutter_y_label"), value=0.0, step=0.5, format="%.2f")
            duplex_in = ui.select(["horizontal", "vertical", "none"], value="horizontal", label=t("duplex_label"))

            def save_calibrated_profile() -> None:
                p_name = profile_name_in.value.strip()
                if not p_name:
                    ui.notify(t("notify_invalid_profile"), type="negative")
                    return

                is_single_doc = int(cols_in.value) == 1 and int(rows_in.value) == 1

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

        # 2. Right Card: Interactive Canvas
        def handle_image_mouse_click(e: Any) -> None:
            nonlocal two_click_mode, first_click_point, last_click_timestamp
            if not two_click_mode:
                return

            now = time.time()
            if now - last_click_timestamp < 0.25:
                return

            raw_x = getattr(e, "image_x", None)
            raw_y = getattr(e, "image_y", None)
            if raw_x is None and hasattr(e, "args") and isinstance(e.args, dict):
                raw_x = e.args.get("image_x")
                raw_y = e.args.get("image_y")

            if raw_x is None or raw_y is None:
                return

            pt_x = round(float(raw_x) / PREVIEW_SCALE, 2)
            pt_y = round(float(raw_y) / PREVIEW_SCALE, 2)

            if first_click_point is None:
                first_click_point = (pt_x, pt_y)
                last_click_timestamp = now
                ox_in.value = pt_x
                oy_in.value = pt_y
                btn_two_click.text = t("two_click_btn_step2")
                trigger_overlay_refresh()
                ui.notify(t("notify_click_1").format(x=pt_x, y=pt_y), type="info")
            else:
                total_w = max(10.0, round(pt_x - first_click_point[0], 2))
                total_h = max(10.0, round(pt_y - first_click_point[1], 2))

                gx_in.value = 0.0
                gy_in.value = 0.0

                if calibration_target == "grid":
                    cols = max(1, int(cols_in.value or 1))
                    rows = max(1, int(rows_in.value or 1))
                    w_in.value = round(total_w / cols, 2)
                    h_in.value = round(total_h / rows, 2)
                else:
                    w_in.value = total_w
                    h_in.value = total_h

                reset_two_click_state()
                ui.notify(t("notify_click_2").format(w=w_in.value, h=h_in.value), type="positive")

        with ui.card().classes("flex-1 q-pa-md items-center justify-center bg-grey-3"):
            preview_image = ui.interactive_image(
                cross=True,
                events=["click"],
                on_mouse=handle_image_mouse_click,
            ).classes("shadow-4")

    # Dialogs
    with ui.dialog() as guide_dialog, ui.card().classes("w-96"):
        ui.label(t("two_click_title")).classes("text-h6 font-bold")
        mode_radio = ui.radio({"card": t("two_click_mode_card"), "grid": t("two_click_mode_grid")}, value="card").classes("q-my-sm")
        ui.markdown(t("two_click_guide_details"))
        with ui.row().classes("w-full justify-end q-mt-md"):
            def start_two_click_session() -> None:
                nonlocal two_click_mode, first_click_point, calibration_target
                two_click_mode = True
                calibration_target = mode_radio.value
                first_click_point = None
                btn_two_click.props("color=warning")
                btn_two_click.text = t("two_click_btn_step1")
                guide_dialog.close()
                ui.notify(t("two_click_prompt_step1"), type="info")

            ui.button(t("btn_cancel"), on_click=guide_dialog.close).props("flat")
            ui.button(t("btn_start"), on_click=start_two_click_session).props("color=primary")

    def toggle_two_click() -> None:
        if two_click_mode:
            reset_two_click_state()
        else:
            guide_dialog.open()

    btn_two_click.on("click", toggle_two_click)

    # -----------------------------------------------------------------------
    # Shortcuts Modal Dialog
    # -----------------------------------------------------------------------
    with ui.dialog() as shortcuts_dialog, ui.card().classes("w-126"):
        ui.label(t("shortcuts_title")).classes("text-h6 font-bold")
        markdown_table = (
            f"| {t('shortcuts_col_key')} | {t('shortcuts_col_action')} |\n"
            f"| :--- | :--- |\n"
            f"| **Arrows (▲ ▼ ◄ ►)** | {t('shortcuts_origin')} |\n"
            f"| **W / A / S / D** | {t('shortcuts_size')} |\n"
            f"| **I / K / J / L** | {t('shortcuts_gutters_ikjl')} |\n"
            f"| **[ / ]** | {t('shortcuts_cols')} |\n"
            f"| **; / '** | {t('shortcuts_rows')} |"
        )
        ui.markdown(markdown_table)
        ui.button(t("btn_close"), on_click=shortcuts_dialog.close).props("flat").classes("self-end")

    btn_shortcuts_help.on("click", shortcuts_dialog.open)

    # Prevent Arrow keys from scrolling the browser window (stateless header injection)
    ui.add_head_html(
        """
        <script>
        window.addEventListener('keydown', function(e) {
            if(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
                e.preventDefault();
            }
        }, false);
        </script>
        """
    )

    # -----------------------------------------------------------------------
    # Throttled Rendering Engine (~25 FPS Cap)
    # -----------------------------------------------------------------------
    def refresh_overlay_sync() -> None:
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
            calibrating_origin=two_click_mode,
            first_click_point=first_click_point,
        )
        preview_image.content = svg

    async def _throttled_refresh_loop() -> None:
        nonlocal _is_refreshing, _needs_refresh
        _is_refreshing = True
        while _needs_refresh:
            _needs_refresh = False
            refresh_overlay_sync()
            await asyncio.sleep(0.04)  # Limit WebSocket transmissions to 25 FPS
        _is_refreshing = False

    def trigger_overlay_refresh() -> None:
        nonlocal _needs_refresh
        _needs_refresh = True
        if not _is_refreshing:
            asyncio.create_task(_throttled_refresh_loop())

    # -----------------------------------------------------------------------
    # Conflict-Free Keyboard Handler
    # -----------------------------------------------------------------------
    def handle_keyboard(e: events.KeyEventArguments) -> None:
        if not e.action.keydown or two_click_mode:
            return

        key_raw = getattr(e.key, "name", e.key)
        key_name = str(key_raw)
        key_lower = key_name.lower()

        step_origin = 0.1 if e.modifiers.shift else 1.0
        step_card = 0.1 if e.modifiers.shift else 1.0
        step_gutter = 0.1 if e.modifiers.shift else 0.5

        # 1. Origin via Arrows (No Ctrl/Alt dependencies)
        if key_name in ("ArrowUp", "Up"):
            oy_in.value = round(float(oy_in.value or 0) - step_origin, 2)
            trigger_overlay_refresh()
        elif key_name in ("ArrowDown", "Down"):
            oy_in.value = round(float(oy_in.value or 0) + step_origin, 2)
            trigger_overlay_refresh()
        elif key_name in ("ArrowLeft", "Left"):
            ox_in.value = round(float(ox_in.value or 0) - step_origin, 2)
            trigger_overlay_refresh()
        elif key_name in ("ArrowRight", "Right"):
            ox_in.value = round(float(ox_in.value or 0) + step_origin, 2)
            trigger_overlay_refresh()

        # 2. Card Size via WASD
        elif key_lower == "w":
            h_in.value = max(10.0, round(float(h_in.value or 0) - step_card, 2))
            trigger_overlay_refresh()
        elif key_lower == "s":
            h_in.value = round(float(h_in.value or 0) + step_card, 2)
            trigger_overlay_refresh()
        elif key_lower == "a":
            w_in.value = max(10.0, round(float(w_in.value or 0) - step_card, 2))
            trigger_overlay_refresh()
        elif key_lower == "d":
            w_in.value = round(float(w_in.value or 0) + step_card, 2)
            trigger_overlay_refresh()

        # 3. Gutters via IKJL (Right-hand cluster, zero OS conflicts)
        elif key_lower == "i":
            gy_in.value = max(0.0, round(float(gy_in.value or 0) - step_gutter, 2))
            trigger_overlay_refresh()
        elif key_lower == "k":
            gy_in.value = round(float(gy_in.value or 0) + step_gutter, 2)
            trigger_overlay_refresh()
        elif key_lower == "j":
            gx_in.value = max(0.0, round(float(gx_in.value or 0) - step_gutter, 2))
            trigger_overlay_refresh()
        elif key_lower == "l":
            gx_in.value = round(float(gx_in.value or 0) + step_gutter, 2)
            trigger_overlay_refresh()

        # 4. Columns & Rows
        elif key_name == "[":
            cols_in.value = max(1, int(cols_in.value or 1) - 1)
            trigger_overlay_refresh()
        elif key_name == "]":
            cols_in.value = min(10, int(cols_in.value or 1) + 1)
            trigger_overlay_refresh()
        elif key_name in (";", ":"):
            rows_in.value = max(1, int(rows_in.value or 1) - 1)
            trigger_overlay_refresh()
        elif key_name in ("'", '"'):
            rows_in.value = min(10, int(rows_in.value or 1) + 1)
            trigger_overlay_refresh()

    ui.keyboard(on_key=handle_keyboard)

    def load_selected_pdf_preview() -> None:
        if not pdf_select.value:
            return
        full_path = pdf_options[pdf_select.value]
        src, width, height = PdfGridAnalyzer.render_page_base64(full_path, 0)
        state.preview_dims["w"] = width
        state.preview_dims["h"] = height
        preview_image.set_source(src)
        trigger_overlay_refresh()

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
        trigger_overlay_refresh()
        ui.notify(t("notify_auto_detect_ok"), type="info")

    for widget in [cols_in, rows_in, w_in, h_in, ox_in, oy_in, gx_in, gy_in]:
        widget.on("update:model-value", trigger_overlay_refresh)

    pdf_select.on("update:model-value", load_selected_pdf_preview)
    auto_btn.on("click", run_auto_detect)

    ui.timer(0.1, load_selected_pdf_preview, once=True)