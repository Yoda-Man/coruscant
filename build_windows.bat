@echo off
setlocal

echo ============================================================
echo  Coruscant v1.1.2 - Windows Build
echo ============================================================

:: Move to the project root (same folder as this script)
cd /d "%~dp0"

:: Clean previous build artefacts
echo.
echo [1/4] Cleaning previous build...
if exist distribution\.build rmdir /s /q distribution\.build
if exist distribution\dist   rmdir /s /q distribution\dist

:: Install / upgrade dependencies
echo.
echo [2/4] Installing dependencies...
:: "python -m pip" rather than the pip shim, so dependencies always land in the
:: same interpreter that runs the build below.
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)
python -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: PyInstaller install failed.
    pause
    exit /b 1
)

:: Run PyInstaller
echo.
echo [3/4] Building executable...
:: Invoked as a module, not via the pyinstaller.exe console shim: an
:: interrupted pip install can leave the package importable but the shim
:: missing, which fails with "'pyinstaller' is not recognized". This also
:: matches how the macOS and Linux CI jobs invoke it.
python -m PyInstaller distribution\coruscant.spec ^
    --distpath distribution\dist ^
    --workpath distribution\.build ^
    --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

:: Report
echo.
echo [4/4] Done.
echo.
if exist distribution\dist\Coruscant.exe (
    for %%F in (distribution\dist\Coruscant.exe) do (
        echo   Output : %~dp0distribution\dist\Coruscant.exe
        echo   Size   : %%~zF bytes
    )
) else (
    echo WARNING: Coruscant.exe not found in distribution\dist\
)

echo.
echo ============================================================
echo  Build complete.
echo ============================================================
pause
endlocal
