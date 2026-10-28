#!/bin/bash
# ---------------------------------------------------------------------------
# Reload the ServeSync demo organization (fresh dates, all demo features).
#
# Use before practice runs and on competition day, so "this week" in the
# demo is always this week. This ERASES everything in ServeSync's data
# folder on this Mac, so it asks you to type YES first.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
finish() {
    echo
    echo "$1"
    echo
    read -n 1 -s -r -p "Press any key to close this window."
    echo
    exit "$2"
}

[ -x .venv/bin/python ] || finish "Run setup_mac.command first." 1
# shellcheck disable=SC1091
source .venv/bin/activate

echo "This erases ALL ServeSync data on this Mac and reloads the demo organization."
read -r -p "Type YES to continue: " answer
[ "$answer" = "YES" ] || finish "Nothing was changed." 0

python devtools.py reset --yes || finish "The demo could not be reloaded (see the messages above)." 1
echo
python devtools.py summary
finish "Done. Double-click ServeSync.command to open the app." 0
