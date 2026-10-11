#!/usr/bin/env bash
set -euo pipefail

# ---------- config ----------
SERVICE_NAME="pw-convert-service"
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backend"
PORT=8055
UV_BIN=$(which uv)
COMMAND="/snap/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 3"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
  echo "Start as root (sudo $0)" >&2
  exit 1
fi

# ---------- user ----------
# Run the service as the user who invoked sudo (not root), so that HOME
# points to their directory instead of /root.
if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
  RUN_USER="${SUDO_USER}"
elif [[ $EUID -ne 0 ]]; then
  RUN_USER="$(id -un)"
else
  RUN_USER="root"
fi

if ! getent passwd "${RUN_USER}" >/dev/null; then
  echo "user not found: ${RUN_USER}" >&2
  exit 1
fi

RUN_GID="$(id -g "${RUN_USER}")"
RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"

if [[ ! -x "$UV_BIN" ]]; then
  echo "uv not found: $UV_BIN" >&2
  exit 1
fi

echo "==> Run service as user '${RUN_USER}' (HOME=${RUN_HOME})"

echo "==> Write unit $UNIT_PATH"

cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Python service (${SERVICE_NAME}) via uv
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GID}
WorkingDirectory=${WORK_DIR}
Environment=PATH=${WORK_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=${RUN_HOME}
Environment=PYTHONUNBUFFERED=1
ExecStart=${COMMAND}
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
