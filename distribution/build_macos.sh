#!/bin/bash
set -e

# Navigate to the project root (parent of this script's directory)
cd "$(dirname "$0")/.."

echo
echo " Coruscant - macOS Build"
echo " ================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo " ERROR: python3 not found. Install Python 3.10+ via python.org or Homebrew."
    exit 1
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

if [ -d "distribution/dist/Coruscant.app" ]; then
    echo
    echo " Packaging .app into zip..."
    cd distribution/dist
    zip -r --quiet Coruscant-macOS.zip Coruscant.app
    cd ../..

    echo
    echo " Done."
    echo " Output: distribution/dist/Coruscant-macOS.zip"
    echo " Size:   $(du -sh distribution/dist/Coruscant-macOS.zip | cut -f1)"
else
    echo
    echo " Build failed. Check the output above for errors."
    exit 1
fi
