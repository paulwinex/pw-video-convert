#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="pw-convert-service"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
  echo "Start as root (sudo $0)" >&2
  exit 1
fi

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  echo "==> stop"
  systemctl stop "${SERVICE_NAME}.service" || true

  echo "==> disable"
  systemctl disable "${SERVICE_NAME}.service" || true
fi

if [[ -f "$UNIT_PATH" ]]; then
  echo "==> deleting $UNIT_PATH..."
  rm -f "$UNIT_PATH"
else
  echo "File $UNIT_PATH not exists"
fi

echo "==> daemon-reload"
systemctl daemon-reload

echo "==> reset-failed"
systemctl reset-failed "${SERVICE_NAME}.service" 2>/dev/null || true

echo "Done"
