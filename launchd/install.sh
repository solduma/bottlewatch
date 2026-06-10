#!/bin/bash
# install.sh — Install bottlewatch launchd agents.
# Idempotent: safe to run multiple times.
#
# The plist file paths are templated at install time: any
# `/Users/iljoyoo/workspace/bottlewatch` substring in the source
# plist is replaced with the install-time `BOTTLEWATCH_ROOT`
# (defaults to the directory above `launchd/`). This way the same
# repo can be installed from any path — not just one developer's
# machine.
#
# The source plist is NEVER modified. The substitution happens on
# a sed-piped copy, so the repo stays clean across installs.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOTTLEWATCH_ROOT="${BOTTLEWATCH_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# The default project path is hard-coded in the bundled plist as
# `/Users/iljoyoo/workspace/bottlewatch`; we substitute it with
# the install-time root.
DEFAULT_PROJECT_PATH="/Users/iljoyoo/workspace/bottlewatch"

install_agent() {
    local name="$1"
    local src="$SCRIPT_DIR/${name}.plist"
    local dst="$LAUNCH_DIR/${name}.plist"
    if [ -f "$dst" ]; then
        # Already loaded — unload first so we pick up any changes.
        launchctl bootout "gui/$(id -u)/${name}" 2>/dev/null || true
    fi
    # Pipe sed straight to cp so the source file is never modified.
    if [ "$BOTTLEWATCH_ROOT" != "$DEFAULT_PROJECT_PATH" ]; then
        sed "s|$DEFAULT_PROJECT_PATH|$BOTTLEWATCH_ROOT|g" "$src" > "$dst"
    else
        cp "$src" "$dst"
    fi
    launchctl load -w "$dst"
    echo "Installed: $dst (root: $BOTTLEWATCH_ROOT)"
}

install_agent com.bottlewatch.refresh
install_agent com.bottlewatch.recompute

echo ""
echo "bottlewatch agents installed. Run 'make unschedule' to remove."
echo "Check with: launchctl list | grep bottlewatch"
