#!/bin/bash
set -e

# Navigate to the project root (parent of this script's directory)
cd "$(dirname "$0")/.."

echo
echo " Coruscant - Linux Build"
echo " ================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo " ERROR: python3 not found. Install Python 3.10+."
    exit 1
fi

# PySide6 requires these system libraries on the build machine.
# They must also be present on any machine running the final binary.
echo " Checking system libraries..."
MISSING=()
for lib in libGL.so.1 libglib-2.0.so.0 libdbus-1.so.3; do
    if ! ldconfig -p 2>/dev/null | grep -q "$lib"; then
        MISSING+=("$lib")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo
    echo " WARNING: The following system libraries were not found:"
    for lib in "${MISSING[@]}"; do echo "   - $lib"; done
    echo
    echo " On Debian/Ubuntu:  sudo apt-get install libgl1 libglib2.0-0 libdbus-1-3"
    echo " On Fedora/RHEL:    sudo dnf install mesa-libGL glib2 dbus-libs"
    echo
    echo " The build may fail or the binary may not run on target machines"
    echo " without these libraries. Press Enter to continue anyway, or Ctrl+C to abort."
    read -r
fi

# Install build dependencies
echo " Installing dependencies..."
pip3 install -r requirements.txt --quiet
pip3 install pyinstaller --quiet

echo " Building..."
echo

python3 -m PyInstaller distribution/coruscant.spec \
    --distpath distribution/dist \
    --workpath distribution/.build \
    --noconfirm

if [ -f "distribution/dist/Coruscant" ]; then
    echo
    echo " Done."
    echo " Output: distribution/dist/Coruscant"
    echo " Size:   $(du -sh distribution/dist/Coruscant | cut -f1)"
else
    echo
    echo " Build failed. Check the output above for errors."
    exit 1
fi
