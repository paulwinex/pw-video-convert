#!/usr/bin/env bash
set -euo pipefail

# ---------- config ----------
SERVICE_NAME="pw-convert-service"

if [[ $EUID -ne 0 ]]; then
  echo "Start as root (sudo $0)" >&2
  exit 1
fi

echo "==> daemon-reload"
systemctl daemon-reload

echo "==> restart"
systemctl restart "${SERVICE_NAME}.service"

echo "==> Status:"
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true

echo
echo "Done. Logs: journalctl -u ${SERVICE_NAME} -f"
