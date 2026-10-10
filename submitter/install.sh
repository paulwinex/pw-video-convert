#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/pw-conv"
SERVICEMENU_DIR="$HOME/.local/share/kio/servicemenus"
DESKTOP_FILE="$SERVICEMENU_DIR/pw.conv.desktop"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
mkdir -p "$SERVICEMENU_DIR"

cp "$SCRIPT_DIR/submitter.py" "$INSTALL_DIR/submitter.py"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=video/*;
Actions=showVideoPathDialog
X-KDE-Priority=TopLevel
Terminal=false

[Desktop Action showVideoPathDialog]
Name=Convert Video
Icon=io.bassi.Amberol
Exec=/usr/bin/python3 $INSTALL_DIR/submitter.py %F
EOF

chmod +x "$DESKTOP_FILE"

echo "Installed:"
echo "  $INSTALL_DIR/submitter.py"
echo "  $DESKTOP_FILE"
