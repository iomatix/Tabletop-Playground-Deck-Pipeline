"""
NiceGUI Desktop Management Interface for the TTPG Deck Pipeline.

Entry-point launcher initializing application layout, views,
and running the local server instance.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Final, Optional

# Pre-flight runtime dependency check
REQUIRED_MODULES: Final[list[str]] = ["pymupdf", "PIL", "nicegui"]
missing = []
for mod in REQUIRED_MODULES:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)

if missing:
    print(
        f"[FAIL-FAST] Missing dependencies: {', '.join(missing)}. "
        f"Install them via: pip install {' '.join(missing)}",
        file=sys.stderr,
    )
    sys.exit(1)

from nicegui import app, ui

from app.state import (
    TTPG_PACKAGES_DIR,
    get_input_dir,
    open_system_folder,
    state,
    t,
)
from app.views.calibrator import create_calibrator_view
from app.views.wizard import create_pipeline_view


def patch_windows_proactor_loop() -> None:
    """Silences noisy WinError 10054 (ConnectionResetError) on Windows Proactor EventLoop."""
    if sys.platform != "win32":
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    original_handler = loop.get_exception_handler()

    def connection_reset_exception_handler(
        current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]
    ) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError) or (
            isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10054
        ):
            return
        if original_handler:
            original_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(connection_reset_exception_handler)


app.on_startup(patch_windows_proactor_loop)


@ui.page("/")
def index_page() -> None:
    # Styl i kolory przeniesione do wnetrza strony (brak kolizji z global scope)
    ui.colors(primary="#1976d2", secondary="#26a69a", accent="#9c27b0", dark="#121212")

    lang_selector_ref: dict[str, Optional[ui.select]] = {"widget": None}

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

            lang_selector = ui.select(
                {"en": "English", "pl": "Polski"},
                value=state.current_lang,
                on_change=handle_language_change,
            ).props("dense borderless dark options-dark").classes("w-28 text-white")
            lang_selector_ref["widget"] = lang_selector

    @ui.refreshable
    def render_dashboard() -> None:
        with ui.tabs().classes("w-full") as tabs:
            tab_pipeline = ui.tab(t("tab_pipeline"))
            tab_calibrator = ui.tab(t("tab_calibrator"))

        with ui.tab_panels(tabs, value=tab_pipeline).classes("w-full max-w-6xl mx-auto q-pa-md"):
            with ui.tab_panel(tab_pipeline):
                create_pipeline_view(lambda: lang_selector_ref["widget"])

            with ui.tab_panel(tab_calibrator):
                create_calibrator_view()

    render_dashboard()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="127.0.0.1",
        port=8080,
        title="TTPG Deck Pipeline Manager",
        native=False,
        reload=False,
    )