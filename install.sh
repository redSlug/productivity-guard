#!/bin/bash
#
# install.sh
# Installs the productivity-guard LaunchAgent for the current user on macOS Sonoma 14.7+.

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$REPO_DIR/productivity_guard.sh"
PLIST_SRC="$REPO_DIR/com.user.productivityguard.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.user.productivityguard.plist"
LABEL="com.user.productivityguard"

echo "REPO_DIR=$REPO_DIR"
echo "SCRIPT_PATH=$SCRIPT_PATH"
echo "PLIST_SRC=$PLIST_SRC"
echo "PLIST_DEST=$PLIST_DEST"
echo "LABEL=$LABEL"

chmod +x "$SCRIPT_PATH"

mkdir -p "$HOME/Library/LaunchAgents"

# Substitute the real script path (plists cannot expand ~ or $HOME).
sed "s|__SCRIPT_PATH__|$SCRIPT_PATH|g" "$PLIST_SRC" > "$PLIST_DEST"

# Unload any previous copy before loading the fresh one.
if launchctl list | grep -q "$LABEL"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

launchctl load "$PLIST_DEST"

echo "Installed $LABEL -> $PLIST_DEST"
echo "productivity_guard.sh will run every 60 seconds via launchd."
