"""
System Diagnostics, Test Runner, and Static Linter View.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Callable, Optional

from nicegui import ui

from app.state import BASE_DIR, state, t


def create_diagnostics_view(lang_selector_ref_getter: Callable[[], Optional[ui.select]]) -> None:
    is_frozen = getattr(sys, "frozen", False)
    pytest_bin = shutil.which("pytest")
    ruff_bin = shutil.which("ruff")

    can_run_pytest = (not is_frozen) or (pytest_bin is not None)
    can_run_ruff = (not is_frozen) or (ruff_bin is not None)

    ui.markdown(f"### {t('diag_title')}")
    ui.markdown(t("diag_desc"))

    if is_frozen and (not can_run_pytest or not can_run_ruff):
        with ui.card().classes("w-full bg-amber-1 border-l-4 border-warning q-pa-sm q-my-sm"):
            ui.label(t("diag_standalone_notice_title")).classes("font-bold text-caption text-warning")
            ui.markdown(t("diag_standalone_notice_desc")).classes("text-caption text-grey-8")
    else:
        with ui.card().classes("w-full bg-blue-grey-1 border-l-4 border-primary q-pa-sm q-my-sm"):
            ui.label(t("diag_notice_title")).classes("font-bold text-caption text-primary")
            ui.markdown(t("diag_notice_desc")).classes("text-caption text-grey-8")

    status_badge = ui.badge(t("diag_status_ready"), color="grey-7").classes("text-body2 q-py-xs q-px-sm")
    log_console = ui.log().classes("w-full h-80 bg-grey-10 text-white font-mono text-caption q-mt-sm")

    test_buttons: list[ui.button] = []
    lint_buttons: list[ui.button] = []
    sync_buttons: list[ui.button] = []

    def set_busy_state(is_busy: bool, badge_text: str = "", badge_color: str = "grey-7") -> None:
        state.is_busy = is_busy
        selector = lang_selector_ref_getter()
        if selector:
            if is_busy:
                selector.disable()
            else:
                selector.enable()

        for btn in test_buttons:
            if is_busy or not can_run_pytest:
                btn.disable()
            else:
                btn.enable()

        for btn in lint_buttons:
            if is_busy or not can_run_ruff:
                btn.disable()
            else:
                btn.enable()

        for btn in sync_buttons:
            if is_busy:
                btn.disable()
            else:
                btn.enable()

        if badge_text:
            status_badge.text = badge_text
            status_badge.props(f"color={badge_color}")

    async def execute_pytest(extra_args: list[str]) -> None:
        if state.is_busy or not can_run_pytest:
            return

        set_busy_state(True, t("diag_status_running"), "blue-7")
        log_console.clear()

        if is_frozen and pytest_bin:
            cmd = [pytest_bin, "-v"] + extra_args
        else:
            cmd = [sys.executable, "-u", "-m", "pytest", "-v"] + extra_args

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(BASE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            while raw_line := await proc.stdout.readline():
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                log_console.push(line)

            await proc.wait()

            if proc.returncode == 0:
                set_busy_state(False, t("diag_status_passed"), "positive")
                ui.notify(t("diag_status_passed"), type="positive")
            else:
                set_busy_state(False, t("diag_status_failed"), "negative")
                ui.notify(t("diag_status_failed"), type="negative")

        except Exception as exc:
            log_console.push(f"[ERROR] Failed to spawn pytest process: {exc}")
            set_busy_state(False, t("diag_status_failed"), "negative")

    async def execute_ruff() -> None:
        if state.is_busy or not can_run_ruff:
            return

        set_busy_state(True, t("diag_status_linting"), "purple-7")
        log_console.clear()
        log_console.push("[START] Executing Ruff static code analysis...")

        if is_frozen and ruff_bin:
            cmd = [ruff_bin, "check", "."]
        else:
            cmd = [sys.executable, "-u", "-m", "ruff", "check", "."]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(BASE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            while raw_line := await proc.stdout.readline():
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                log_console.push(line)

            await proc.wait()

            if proc.returncode == 0:
                log_console.push("[SUCCESS] Ruff check completed with zero errors.")
                set_busy_state(False, t("diag_lint_passed"), "positive")
                ui.notify(t("diag_lint_passed"), type="positive")
            else:
                log_console.push(f"[FAILURE] Ruff reported issues (exit code: {proc.returncode}).")
                set_busy_state(False, t("diag_lint_failed"), "negative")
                ui.notify(t("diag_lint_failed"), type="negative")

        except Exception as exc:
            log_console.push(f"[ERROR] Failed to execute Ruff: {exc}")
            set_busy_state(False, t("diag_lint_failed"), "negative")

    def run_locale_sync() -> None:
        if state.is_busy:
            return

        from tests.test_localization import _sync_and_sort_locales

        en_p = BASE_DIR / "locales" / "en.json"
        pl_p = BASE_DIR / "locales" / "pl.json"
        m_en, m_pl = _sync_and_sort_locales(en_p, pl_p)

        log_console.clear()
        log_console.push("[AUTO-SYNC] Formatted and sorted all locales.")
        if m_en:
            log_console.push(f"[TODO EN] Injected: {m_en}")
        if m_pl:
            log_console.push(f"[TODO PL] Injected: {m_pl}")
        if not m_en and not m_pl:
            log_console.push("[OK] All locale dictionaries are 100% in sync.")

        ui.notify(t("notify_locales_synced"), type="positive")

    with ui.row().classes("items-center gap-3 q-my-sm"):
        btn_all = ui.button(
            t("btn_run_all_tests"),
            icon="checklist",
            on_click=lambda: execute_pytest(["tests/"]),
        ).props("color=primary")

        btn_fast = ui.button(
            t("btn_run_fast_tests"),
            icon="flash_on",
            on_click=lambda: execute_pytest(
                [
                    "tests/test_smoke.py",
                    "tests/test_localization.py",
                    "tests/test_pdf_analyzer.py",
                    "tests/test_packager_install.py",
                ]
            ),
        ).props("outline color=secondary")

        btn_install_test = ui.button(
            t("diag_btn_test_installer"),
            icon="install_desktop",
            on_click=lambda: execute_pytest(["tests/test_packager_install.py"]),
        ).props("outline color=teal")

        btn_linter = ui.button(
            t("btn_run_linter"),
            icon="policy",
            on_click=execute_ruff,
        ).props("outline color=purple")

        btn_sync = ui.button(
            t("btn_sync_locales"),
            icon="auto_fix_normal",
            on_click=run_locale_sync,
        ).props("outline color=grey-8")

        test_buttons.extend([btn_all, btn_fast, btn_install_test])
        lint_buttons.append(btn_linter)
        sync_buttons.append(btn_sync)

        if not can_run_pytest:
            for b in test_buttons:
                b.disable()

        if not can_run_ruff:
            for b in lint_buttons:
                b.disable()