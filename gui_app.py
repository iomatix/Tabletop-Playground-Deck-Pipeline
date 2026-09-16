"""
NiceGUI Desktop Management Interface for the TTPG Deck Pipeline.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Final, Optional


# --- 1. Global Fatal Crash Handler ---
def _install_crash_handler() -> None:
    if getattr(sys, "frozen", False):
        log_dir = Path(sys.executable).resolve().parent
    else:
        log_dir = Path(__file__).resolve().parent

    crash_log_file = log_dir / "crash_log.txt"

    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        with open(crash_log_file, "w", encoding="utf-8") as f:
            f.write("=== FATAL CRASH LOG ===\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)

        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception


_install_crash_handler()

# --- 2. CLI Dispatcher for Frozen Executables ---
if getattr(sys, "frozen", False) and len(sys.argv) > 1:
    target_cmd = sys.argv[1].lower()
    if "deck_processor" in target_cmd:
        import deck_processor

        deck_processor.main()
        sys.exit(0)
    elif "ttpg_packager" in target_cmd:
        import ttpg_packager

        ttpg_packager.main()
        sys.exit(0)

# --- 3. Pre-flight Runtime Dependency Check ---
REQUIRED_MODULES: Final[list[str]] = ["pymupdf", "PIL", "nicegui"]
missing = []
for mod in REQUIRED_MODULES:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)

if missing:
    print(
        f"[FAIL-FAST] Missing dependencies: {', '.join(missing)}. Install them via: pip install {' '.join(missing)}",
        file=sys.stderr,
    )
    sys.exit(1)

# --- 4. Application Logic ---
from nicegui import ui

from app.state import (
    SUPPORTED_LOCALES,
    change_language,
    current_lang,
    t,
)
from app.views.calibrator import create_calibrator_view
from app.views.diagnostics import create_diagnostics_view
from app.views.wizard import create_pipeline_view


@ui.page("/")
def main_page() -> None:
    ui.colors(
        primary="#1976D2",
        secondary="#26A69A",
        accent="#9C27B0",
        positive="#21BA45",
        negative="#C10015",
        info="#31CCEC",
        warning="#F2C037",
    )

    lang_selector: Optional[ui.select] = None

    def get_lang_selector() -> Optional[ui.select]:
        return lang_selector

    with ui.header().classes("items-center justify-between bg-primary text-white q-px-md"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("layers", size="md")
            ui.label(t("app_title")).classes("text-h6 font-bold tracking-wider")

        with ui.row().classes("items-center gap-4"):
            lang_selector = (
                ui.select(
                    options=SUPPORTED_LOCALES,
                    value=current_lang,
                    on_change=lambda e: change_language(e.value),
                )
                .props("dense outlined dark bg-color=primary-dark options-dense")
                .classes("w-28 text-caption")
            )

    with ui.tabs().classes("w-full bg-grey-2 text-primary shadow-1") as tabs:
        tab_wizard = ui.tab(t("tab_wizard"), icon="auto_fix_high")
        tab_calibrator = ui.tab(t("tab_calibrator"), icon="tune")
        tab_diagnostics = ui.tab(t("tab_diagnostics"), icon="troubleshoot")

    with ui.tab_panels(tabs, value=tab_wizard).classes("w-full p-4"):
        with ui.tab_panel(tab_wizard):
            create_pipeline_view(get_lang_selector)

        with ui.tab_panel(tab_calibrator):
            create_calibrator_view()

        with ui.tab_panel(tab_diagnostics):
            create_diagnostics_view(get_lang_selector)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="TTPG Deck Pipeline Manager",
        favicon="🃏",
        reload=False,
        show=True,
    )
