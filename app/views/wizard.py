"""
Pipeline Execution Stepper View (4-Step Wizard).

Coordinates sequential deck processing: configuration, extraction, packaging,
and TTPG package installation with strict UI state protection and diagnostic telemetry.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
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


def check_package_ready(pkg_dir: str, pkg_name: str) -> tuple[bool, str]:
    target = BASE_DIR / pkg_dir / pkg_name
    manifest = target / "Manifest.json"
    templates_dir = target / "Templates"
    textures_dir = target / "Textures"

    if not manifest.exists():
        return False, t("status_no_manifest")

    n_templates = len(list(templates_dir.glob("*.json"))) if templates_dir.exists() else 0
    n_textures = len(list(textures_dir.glob("*.png"))) if textures_dir.exists() else 0

    if n_templates == 0 or n_textures == 0:
        return False, f"{t('status_incomplete_assets')} (Templates: {n_templates}, Textures: {n_textures})"

    return True, f"{t('status_valid_package')} ({n_templates} templates, {n_textures} textures)"


def create_pipeline_view(lang_selector_ref_getter: Callable[[], Optional[ui.select]]) -> None:
    with ui.stepper().props('vertical :header-nav="false"').classes("w-full") as stepper:
        # -------------------------------------------------------------------
        # Step 1: Configuration
        # -------------------------------------------------------------------
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

        # -------------------------------------------------------------------
        # Step 2: Extraction
        # -------------------------------------------------------------------
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
                btn_back_extract.disable()

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
                    btn_back_extract.enable()

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
                btn_back_extract = ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

        # -------------------------------------------------------------------
        # Step 3: Packaging
        # -------------------------------------------------------------------
        with ui.step(t("step_3_title")):
            ui.markdown(t("step_3_desc"))

            pkg_status_label = ui.label("").classes("text-caption font-mono q-mb-sm")
            with ui.row().classes("items-center gap-2 q-mb-md"):
                pkg_status_badge = ui.badge("", color="grey-7").classes("text-caption")
                btn_skip_to_install = ui.button(
                    t("btn_save_and_next"),
                    on_click=stepper.next,
                ).props("flat color=secondary icon-right=arrow_forward")

            def refresh_package_status() -> bool:
                is_ready, msg = check_package_ready(pkg_dir_in.value, pkg_name_in.value)
                pkg_status_label.text = msg
                if is_ready:
                    pkg_status_badge.text = t("status_ready")
                    pkg_status_badge.props("color=positive")
                    btn_skip_to_install.enable()
                else:
                    pkg_status_badge.text = t("status_not_compiled")
                    pkg_status_badge.props("color=grey-7")
                    btn_skip_to_install.disable()
                return is_ready

            pkg_name_in.on("change", refresh_package_status)
            pkg_dir_in.on("change", refresh_package_status)
            refresh_package_status()

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
                btn_back_pack.disable()
                btn_skip_to_install.disable()

                pkg_status_badge.text = t("status_compiling")
                pkg_status_badge.props("color=warning")
                pkg_status_label.text = t("status_packaging_in_progress")

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
                        refresh_package_status()
                        stepper.next()
                    else:
                        ui.notify(t("notify_package_fail"), type="negative")
                        refresh_package_status()
                finally:
                    state.is_busy = False
                    if selector:
                        selector.enable()
                    btn_pack.enable()
                    btn_back_pack.enable()

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
                btn_back_pack = ui.button(t("btn_back"), on_click=stepper.previous).props("flat")

        # -------------------------------------------------------------------
        # Step 4: Installation
        # -------------------------------------------------------------------
        with ui.step(t("step_4_title")):
            ui.markdown(t("step_4_desc"))

            ui.label(t("wizard_install_diag_label")).classes("text-caption text-grey-7 font-bold")
            install_log = ui.log().classes("w-full h-48 bg-grey-10 text-white font-mono text-caption q-my-sm rounded")

            def run_install_with_diagnostics() -> None:
                btn_install_direct.disable()
                install_log.clear()
                install_log.push("[INIT] Starting installation sequence...")

                try:
                    raw_pkg_dir = Path(pkg_dir_in.value.strip())
                    raw_pkg_name = pkg_name_in.value.strip()

                    install_log.push(f"[DEBUG] Input pkg_dir: {raw_pkg_dir}")
                    install_log.push(f"[DEBUG] Input pkg_name: {raw_pkg_name}")
                    install_log.push(f"[DEBUG] TTPG_PACKAGES_DIR: {TTPG_PACKAGES_DIR}")

                    candidates: list[Path] = [
                        BASE_DIR / raw_pkg_dir / raw_pkg_name,
                        BASE_DIR / raw_pkg_dir,
                        raw_pkg_dir if raw_pkg_dir.is_absolute() else (BASE_DIR / raw_pkg_dir),
                    ]

                    package_root = BASE_DIR / "_PACKAGE"
                    if package_root.exists():
                        for folder in package_root.iterdir():
                            if folder.is_dir() and folder not in candidates:
                                candidates.append(folder)

                    source_pkg: Path | None = None
                    for cand in candidates:
                        manifest = cand / "Manifest.json"
                        install_log.push(f"[PROBE] Checking: {cand} -> Manifest: {manifest.exists()}")
                        if manifest.exists():
                            source_pkg = cand
                            break

                    if not source_pkg:
                        install_log.push("[ERROR] Could not locate any directory containing 'Manifest.json'!")
                        ui.notify(t("notify_no_package"), type="negative")
                        return

                    final_name = raw_pkg_name or source_pkg.name
                    target_dest = TTPG_PACKAGES_DIR / final_name

                    install_log.push(f"[RESOLVED] Source: {source_pkg}")
                    install_log.push(f"[RESOLVED] Destination: {target_dest}")

                    TTPG_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
                    install_log.push(f"[FS] Target base ensured: {TTPG_PACKAGES_DIR}")

                    # Purge previous installations to avoid orphaned assets
                    if target_dest.exists():
                        install_log.push(f"[CLEAN] Purging existing target assets in: {target_dest.name}")
                        shutil.rmtree(target_dest)

                    target_dest.mkdir(parents=True, exist_ok=True)

                    total_copied = 0
                    for item in source_pkg.rglob("*"):
                        rel_path = item.relative_to(source_pkg)
                        dest_item = target_dest / rel_path

                        if item.is_dir():
                            dest_item.mkdir(parents=True, exist_ok=True)
                        else:
                            dest_item.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dest_item)
                            total_copied += 1

                    install_log.push(f"[SUCCESS] Copied {total_copied} file(s) into {target_dest}")

                    dest_manifest = target_dest / "Manifest.json"
                    if dest_manifest.exists():
                        install_log.push("[VERIFY] Manifest.json confirmed in target folder.")
                        ui.notify(f"{t('notify_install_ok')}: {final_name}", type="positive")
                    else:
                        install_log.push("[FAIL] Manifest.json missing after copy operation!")
                        ui.notify(t("notify_install_manifest_missing"), type="warning")

                except Exception as exc:
                    install_log.push(f"[EXCEPTION] {type(exc).__name__}: {exc}")
                    ui.notify(f"{t('notify_install_fail')} ({exc})", type="negative")
                finally:
                    btn_install_direct.enable()

            with ui.row().classes("gap-3 q-my-sm"):
                btn_install_direct = ui.button(
                    t("btn_install_direct"),
                    icon="download_done",
                    on_click=run_install_with_diagnostics,
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

            with ui.stepper_navigation():
                ui.button(t("btn_back"), on_click=stepper.previous).props("flat")
