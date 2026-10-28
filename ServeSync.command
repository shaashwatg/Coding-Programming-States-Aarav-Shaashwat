#!/bin/bash
# ---------------------------------------------------------------------------
# Double-click to open ServeSync on a Mac.
# (Run setup_mac.command once first; it installs everything ServeSync needs.)
# ---------------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "ServeSync isn't set up on this Mac yet. Double-click setup_mac.command first."
    read -n 1 -s -r -p "Press any key to close this window."
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Opening ServeSync... (you can minimize this window; closing it also closes ServeSync)"
python main.py
status=$?
if [ $status -ne 0 ]; then
    echo
    echo "ServeSync closed unexpectedly (code $status). Details are in the ServeSync log file."
    read -n 1 -s -r -p "Press any key to close this window."
fi
exit $status
