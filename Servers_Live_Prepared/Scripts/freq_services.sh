#!/usr/bin/env bash
set -euo pipefail

# Auto-detect target Linux user:
# - Normal run: uses current user
# - Run via sudo: uses SUDO_USER
# - Manual override: FT_USER=someuser bash freq_services.sh
TARGET_USER="${FT_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
  echo "[ERROR] Could not detect a non-root target user."
  echo "Run as a normal user with sudo access, or force it with:"
  echo "  FT_USER=youruser bash freq_services.sh"
  exit 1
fi

TARGET_GROUP="$(id -gn "${TARGET_USER}")"
HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6 || true)"

if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
  echo "[ERROR] Could not detect home directory for user: ${TARGET_USER}"
  exit 1
fi

MAX_INSTANCES="${MAX_INSTANCES:-8}"
FREQ_BASE="${FREQ_BASE:-${HOME_DIR}/Servers}"
FREQ_DIR="${FREQ_DIR:-${FREQ_BASE}/Freqtrade}"

echo "================== Target user =================="
echo "User:       ${TARGET_USER}"
echo "Group:      ${TARGET_GROUP}"
echo "Home:       ${HOME_DIR}"
echo "Freq base:  ${FREQ_BASE}"
echo

echo "==================[1/3] Install hardened systemd services =================="

for N in $(seq 1 "${MAX_INSTANCES}"); do
  if [[ ! -f "${FREQ_BASE}/start-${N}.sh" ]]; then
    echo "Skipping instance ${N} - missing ${FREQ_BASE}/start-${N}.sh"
    continue
  fi

  sudo chmod +x "${FREQ_BASE}/start-${N}.sh"
  sudo chown "${TARGET_USER}:${TARGET_GROUP}" "${FREQ_BASE}/start-${N}.sh" || true

  sudo tee "/etc/systemd/system/freqtrade-${N}.service" >/dev/null <<EOF
[Unit]
Description=Freqtrade instance ${N}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_GROUP}
WorkingDirectory=${FREQ_BASE}
ExecStart=${FREQ_BASE}/start-${N}.sh
Restart=always
RestartSec=15
Nice=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
MemoryMax=1200M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

  echo "Created /etc/systemd/system/freqtrade-${N}.service"
done

echo "==================[2/3] Reload systemd =================="
sudo systemctl daemon-reload

echo "==================[3/3] Enable detected instances =================="
for N in $(seq 1 "${MAX_INSTANCES}"); do
  if [[ -f "${FREQ_BASE}/start-${N}.sh" ]]; then
    sudo systemctl enable "freqtrade-${N}.service" || true
  fi
done

echo "================== DONE =================="
echo "Next:"
echo "  - Start : sudo systemctl start freqtrade-1"
echo "  - Status: systemctl status freqtrade-1"
echo "  - Logs  : journalctl -u freqtrade-1 -f"
