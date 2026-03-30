@echo off
setlocal EnableDelayedExpansion

:: Navigate to the project root (parent of this script's directory)
cd /d "%~dp0.."

echo.
echo  Coruscant - Windows Build
echo  ================================
echo.

:: Check Python is available
where python >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.10+ and add it to PATH.
    exit /b 1
)

:: Install build dependencies
echo  Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

echo  Building...
echo.

pyinstaller distribution\coruscant.spec ^
    --distpath distribution\dist ^
    --workpath distribution\.build ^
    --noconfirm

if exist "distribution\dist\Coruscant.exe" (
    echo.
    echo  Done.
    echo  Output: distribution\dist\Coruscant.exe
    for %%A in ("distribution\dist\Coruscant.exe") do echo  Size:   %%~zA bytes
) else (
    echo.
    echo  Build failed. Check the output above for errors.
    exit /b 1
)

endlocal
