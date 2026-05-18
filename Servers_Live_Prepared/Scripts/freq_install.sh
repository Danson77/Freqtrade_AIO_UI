#!/usr/bin/env bash
set -euo pipefail

# Auto-detect target Linux user:
# - Normal run: uses current user
# - Run via sudo: uses SUDO_USER
# - Manual override: FT_USER=someuser bash freq_install.sh
TARGET_USER="${FT_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
  echo "[ERROR] Could not detect a non-root target user."
  echo "Run as a normal user with sudo access, or force it with:"
  echo "  FT_USER=youruser bash freq_install.sh"
  exit 1
fi

TARGET_GROUP="$(id -gn "${TARGET_USER}")"
HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6 || true)"

if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
  echo "[ERROR] Could not detect home directory for user: ${TARGET_USER}"
  exit 1
fi

FREQ_BASE="${FREQ_BASE:-${HOME_DIR}/Servers}"
FREQ_DIR="${FREQ_DIR:-${FREQ_BASE}/Freqtrade}"
VENV_DIR="${FREQ_DIR}/.venv"

INSTALL_DEV_DEPS="${INSTALL_DEV_DEPS:-n}"
INSTALL_PLOTTING="${INSTALL_PLOTTING:-n}"
INSTALL_HYPEROPT="${INSTALL_HYPEROPT:-n}"
INSTALL_FREQAI="${INSTALL_FREQAI:-n}"

MAX_INSTANCES="${MAX_INSTANCES:-3}"

echo "================== Target user =================="
echo "User:       ${TARGET_USER}"
echo "Group:      ${TARGET_GROUP}"
echo "Home:       ${HOME_DIR}"
echo "Freq base:  ${FREQ_BASE}"
echo "Freq dir:   ${FREQ_DIR}"
echo

echo "==================[1/8] Update + install dependencies"
sudo apt update
sudo apt install -y \
  python3-pip python3-venv python3-dev python3-pandas \
  git curl libopenblas-dev cmake libffi-dev ca-certificates

echo "==================[2/8] Prepare directories"
sudo install -d -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${FREQ_BASE}"

echo "==================[3/8] Clone Freqtrade repo (if missing)"
if [[ ! -d "${FREQ_DIR}/.git" ]]; then
  sudo -u "${TARGET_USER}" git clone https://github.com/freqtrade/freqtrade.git "${FREQ_DIR}"
fi

echo "==================[4/8] Checkout stable branch"
cd "${FREQ_DIR}"
sudo -u "${TARGET_USER}" git fetch --all --prune
sudo -u "${TARGET_USER}" git checkout stable
sudo -u "${TARGET_USER}" git pull --ff-only

echo "==================[5/8] Configure pip for target user only"
sudo -u "${TARGET_USER}" mkdir -p "${HOME_DIR}/.config/pip"
sudo -u "${TARGET_USER}" tee "${HOME_DIR}/.config/pip/pip.conf" >/dev/null <<'EOF'
[global]
extra-index-url = https://www.piwheels.org/simple
EOF

echo "==================[6/8] Run Freqtrade setup script"
sudo chmod +x "${FREQ_DIR}/setup.sh"
sudo -u "${TARGET_USER}" bash -c "cd '${FREQ_DIR}' && printf '%s\n' \
  '${INSTALL_DEV_DEPS}' \
  '${INSTALL_PLOTTING}' \
  '${INSTALL_HYPEROPT}' \
  '${INSTALL_FREQAI}' \
  | ./setup.sh -i"

if [[ ! -x "${VENV_DIR}/bin/freqtrade" ]]; then
  echo "[ERROR] Freqtrade binary not found at ${VENV_DIR}/bin/freqtrade"
  echo "[ERROR] setup.sh likely failed or changed behavior."
  exit 1
fi

echo "==================[7/8] Validate start scripts"
for N in $(seq 1 "${MAX_INSTANCES}"); do
  if [[ ! -f "${FREQ_BASE}/start-${N}.sh" ]]; then
    echo "==================WARN: Missing ${FREQ_BASE}/start-${N}.sh (skipping instance ${N})"
    continue
  fi

  sudo chmod +x "${FREQ_BASE}/start-${N}.sh"
  sudo chown "${TARGET_USER}:${TARGET_GROUP}" "${FREQ_BASE}/start-${N}.sh" || true

  if ! grep -q "freqtrade" "${FREQ_BASE}/start-${N}.sh"; then
    echo "[WARN] ${FREQ_BASE}/start-${N}.sh does not appear to call freqtrade"
  fi
done

echo "==================[8/8] Install hardened systemd services"
for N in $(seq 1 "${MAX_INSTANCES}"); do
  if [[ ! -f "${FREQ_BASE}/start-${N}.sh" ]]; then
    continue
  fi

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
done

sudo systemctl daemon-reload

echo "================== Enable default instance =================="
sudo systemctl enable freqtrade-1.service || true

echo "================== DONE =================="
echo "Next:"
echo "  - Copy user_data into ${FREQ_DIR}/user_data/"
echo "  - Check configs/ports in start scripts inside ${FREQ_BASE}"
echo "  - Start: sudo systemctl start freqtrade-1"
echo "  - Logs : journalctl -u freqtrade-1 -f"
