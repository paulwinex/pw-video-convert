#!/usr/bin/env bash
set -euo pipefail

# ---------- config ----------
SERVICE_NAME="pw-convert-service"
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8055
UV_BIN=$(which uv)
RUN_USER="${UID}"
RUN_GROUP="$(id -g)"
ENTRYPOINT="uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 3"
EXTRA_ARGS=""                             # доп. аргументы, если нужны
echo $RUN_GROUP $RUN_USER $WORK_DIR

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
  echo "Start as root (sudo $0)" >&2
  exit 1
fi

if [[ ! -x "$UV_BIN" ]]; then
  echo "uv not found: $UV_BIN" >&2
  exit 1
fi

echo "==> Write unit $UNIT_PATH"

cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Python service (${SERVICE_NAME}) via uv
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${WORK_DIR}
Environment=PATH=${WORK_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=${UV_BIN} run python ${ENTRYPOINT} ${EXTRA_ARGS}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF


echo "==> daemon-reload"
systemctl daemon-reload

echo "==> enable + start"
systemctl enable --now "${SERVICE_NAME}.service"

echo "==> Status:"
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true

echo
echo "Done. Logs: journalctl -u ${SERVICE_NAME} -f"
