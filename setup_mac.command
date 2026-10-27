#!/bin/bash
# ---------------------------------------------------------------------------
# ServeSync one-click setup for macOS
#
# Double-click this file in Finder. A Terminal window opens and:
#   1. finds Python 3.10 or newer on this Mac
#   2. creates a private environment in .venv (nothing is installed system-wide)
#   3. installs the project's libraries (PySide6, pytest, ruff, mypy, PyInstaller)
#   4. loads the demo organization (only if there is no data yet)
#   5. runs the automated tests
#
# Safe to run again at any time. Everything shown is also saved to
# setup_log.txt in this folder.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
exec > >(tee setup_log.txt) 2>&1

finish() {
    echo
    echo "$1"
    echo
    read -n 1 -s -r -p "Press any key to close this window."
    echo
    exit "$2"
}

echo "=== ServeSync setup ($(date '+%Y-%m-%d %H:%M')) ==="
echo

# --- 1. Find Python 3.10+ (PySide6 6.11 supports 3.10 through 3.14) --------
find_python() {
    local candidate path
    for candidate in python3.12 python3.13 python3.11 python3.14 python3.10 \
                     "$HOME/miniforge3/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                     /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
        path=$(command -v "$candidate" 2>/dev/null) || continue
        if "$path" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python) || finish "Python 3.10 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/ and double-click this file again." 1
echo "Using Python: $PYTHON ($("$PYTHON" --version 2>&1))"

# --- 2. Private environment -------------------------------------------------
if [ ! -x .venv/bin/python ]; then
    echo "Creating a private environment in .venv ..."
    "$PYTHON" -m venv .venv || finish "Could not create the .venv environment (see the messages above)." 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- 3. Libraries -----------------------------------------------------------
echo
echo "Installing libraries. The first run downloads PySide6 (several hundred MB), so this can take a few minutes..."
python -m pip install --upgrade pip --quiet || finish "Could not reach the internet to install libraries. Check your Wi-Fi and try again." 1
python -m pip install -r requirements-dev.txt || finish "Library installation failed (see the messages above)." 1

# --- 4. Demo data -----------------------------------------------------------
echo
python devtools.py seed --if-empty || finish "Could not load the demo data (see the messages above)." 1
echo
python devtools.py summary || finish "Could not read the database (see the messages above)." 1

# --- 5. Tests ---------------------------------------------------------------
echo
echo "Running the automated tests..."
if python -m pytest; then
    finish "SUCCESS: ServeSync is set up on this Mac." 0
else
    finish "Some tests failed (see above). Tell Claude, or share setup_log.txt from this folder." 1
fi
