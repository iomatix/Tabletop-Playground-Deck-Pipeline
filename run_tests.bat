@echo off
setlocal
title TTPG Deck Pipeline Test Runner
cd /d "%~dp0"

echo [1/4] Checking Python environment...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in the PATH variable.
    pause
    exit /b 1
)

echo [2/4] Verifying and installing test dependencies...
python -m pip install -r requirements.txt --quiet
python -m pip install pytest ruff --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install test dependencies.
    pause
    exit /b 1
)

echo [3/4] Running Ruff Linter...
echo.
python -m ruff check .
if %errorlevel% neq 0 (
    echo [WARN] Ruff found code issues!
) else (
    echo [OK] Code style and imports verified.
)
echo.

echo [4/4] Running Pytest test suite...
echo.
python -m pytest -v
echo.
if %errorlevel% equ 0 (
    echo ========================================
    echo  [SUCCESS] All pipeline tests passed!
    echo ========================================
) else (
    echo ========================================
    echo  [FAILURE] Tests encountered errors!
    echo ========================================
)

pause