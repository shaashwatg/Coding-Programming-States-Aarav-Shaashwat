#!/bin/bash
# ---------------------------------------------------------------------------
# Build ServeSync.app — a standalone Mac app that needs no Python.
#
# Double-click this file after setup_mac.command has run once. In a few
# minutes, dist/ServeSync.app appears; drag it to Applications or run it
# straight from the folder. Output is also saved to build_log.txt.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
exec > >(tee build_log.txt) 2>&1

finish() {
    echo
    echo "$1"
    echo
    read -n 1 -s -r -p "Press any key to close this window."
    echo
    exit "$2"
}

echo "=== ServeSync app build ($(date '+%Y-%m-%d %H:%M')) ==="
[ -x .venv/bin/python ] || finish "Run setup_mac.command first (it installs the build tools)." 1
# shellcheck disable=SC1091
source .venv/bin/activate

echo "1/4  Checking the code (tests must pass before we build)..."
python -m pytest -q || finish "Tests failed, so the app was not built. See the messages above." 1

echo "2/4  Making the app icon..."
rm -rf build/ServeSync.iconset
python tools/make_icon.py build/ServeSync.iconset || finish "Could not draw the icon." 1
iconutil -c icns build/ServeSync.iconset -o build/ServeSync.icns || echo "   (icon step skipped; the app will use a default icon)"

echo "3/4  Building ServeSync.app (this takes a few minutes)..."
python -m PyInstaller --noconfirm --clean servesync.spec || finish "The build failed (see above)." 1

echo "4/4  Checking the result..."
[ -d dist/ServeSync.app ] || finish "dist/ServeSync.app was not created." 1
du -sh dist/ServeSync.app
finish "SUCCESS: dist/ServeSync.app is ready. Double-click it to run ServeSync without Python." 0
