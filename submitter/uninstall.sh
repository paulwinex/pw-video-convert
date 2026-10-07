#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/pw-conv"
DESKTOP_FILE="$HOME/.local/share/kio/servicemenus/pw.conv.desktop"

if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo "Deleted: $DESKTOP_FILE"
else
    echo "Not found: $DESKTOP_FILE"
fi
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "Deleted: $INSTALL_DIR"
else
    echo "Not found: $INSTALL_DIR"
fi

rmdir --ignore-fail-on-non-empty "$HOME/.local/share/kio/servicemenus" 2>/dev/null || true
rmdir --ignore-fail-on-non-empty "$HOME/.local/share/kio" 2>/dev/null || true

echo "Uninstalled"
