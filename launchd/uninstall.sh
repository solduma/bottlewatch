#!/bin/bash
# uninstall.sh — Remove bottlewatch launchd agents.

set -e

LAUNCH_DIR="$HOME/Library/LaunchAgents"

uninstall_agent() {
    local name="$1"
    local dst="$LAUNCH_DIR/${name}.plist"
    if [ -f "$dst" ]; then
        launchctl bootout "gui/$(id -u)/${name}" 2>/dev/null || true
        launchctl unload -w "$dst" 2>/dev/null || true
        rm -f "$dst"
        echo "Removed: $dst"
    else
        echo "Not installed: $dst"
    fi
}

uninstall_agent com.bottlewatch.daily
uninstall_agent com.bottlewatch.refresh
uninstall_agent com.bottlewatch.recompute

# After uninstall, the source plist may still contain the
# install-time `BOTTLEWATCH_ROOT` if a previous install.sh
# templated the source file (older behavior). This sed restores
# the canonical default path. No-op if the source is already
# in its default form.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOTTLEWATCH_ROOT="${BOTTLEWATCH_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
DEFAULT_PROJECT_PATH="/Users/iljoyoo/workspace/bottlewatch"
if [ "$BOTTLEWATCH_ROOT" != "$DEFAULT_PROJECT_PATH" ]; then
    for plist in "$SCRIPT_DIR"/com.bottlewatch.*.plist; do
        if [ -f "$plist" ] && grep -q "$BOTTLEWATCH_ROOT" "$plist"; then
            sed -i '' "s|$BOTTLEWATCH_ROOT|$DEFAULT_PROJECT_PATH|g" "$plist"
        fi
    done
fi

echo ""
echo "bottlewatch agents removed."