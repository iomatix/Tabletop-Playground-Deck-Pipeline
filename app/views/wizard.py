"""
Pipeline Execution Stepper View (4-Step Wizard).
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Callable, Optional

from nicegui import ui

from app.state import (
    BASE_DIR,
    TTPG_PACKAGES_DIR,
    ConfigRepository,
    config_data,
    open_system_folder,
    state,
    t,
)


def create_pipeline_view(lang_selector_ref_getter: Callable[[], Optional[ui.select]]) -> None:
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
                selector = lang_selector_ref_getter()
                if selector:
                    selector.disable()
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
                    if selector:
                        selector.enable()
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
                selector = lang_selector_ref_getter()
                if selector:
                    selector.disable()
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
                    if selector:
                        selector.enable()
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