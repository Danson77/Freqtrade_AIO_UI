#!/usr/bin/env bash
set -euo pipefail

# Auto-detect target Linux user:
# - Normal run: current user
# - Run via sudo: original sudo user
# - Manual override: FT_USER=someuser bash fan_install.sh
TARGET_USER="${FT_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
  echo "[ERROR] Could not detect a non-root target user."
  echo "Run as a normal user with sudo access, or force it with:"
  echo "  FT_USER=youruser bash fan_install.sh"
  exit 1
fi

if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "[ERROR] Target user does not exist: ${TARGET_USER}"
  exit 1
fi

TARGET_GROUP="$(id -gn "${TARGET_USER}")"
HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6 || true)"

if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
  echo "[ERROR] Could not detect home directory for user: ${TARGET_USER}"
  exit 1
fi

FAN_DIR="${FAN_DIR:-${HOME_DIR}/Fan}"
SERVICE_SRC="${FAN_DIR}/fan-control.service"
PY_SRC="${FAN_DIR}/fan_ctrl.py"
SERVICE_DST="/etc/systemd/system/fan-control.service"

printf '%s\n' "================== Target user =================="
printf 'User:    %s\n' "${TARGET_USER}"
printf 'Group:   %s\n' "${TARGET_GROUP}"
printf 'Home:    %s\n' "${HOME_DIR}"
printf 'Fan dir: %s\n' "${FAN_DIR}"
echo

printf '%s\n' "==================[1/4] Disable serial console + UART (free GPIO14)"
CMDLINE="/boot/firmware/cmdline.txt"
if [[ -f "${CMDLINE}" ]]; then
  sudo sed -i 's/console=serial0,115200 //g' "${CMDLINE}" || true
  sudo sed -i 's/console=ttyAMA0,115200 //g' "${CMDLINE}" || true
else
  echo "==================WARN: ${CMDLINE} not found"
fi

CFG="/boot/firmware/config.txt"
if [[ -f "${CFG}" ]]; then
  sudo sed -i 's/^enable_uart=.*/enable_uart=0/g' "${CFG}" || true
  grep -q '^enable_uart=' "${CFG}" || echo 'enable_uart=0' | sudo tee -a "${CFG}" >/dev/null
else
  echo "==================WARN: ${CFG} not found"
fi

sudo systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
sudo systemctl disable --now serial-getty@ttyS0.service 2>/dev/null || true

printf '%s\n' "==================[2/4] Install dependencies"
sudo apt update
sudo apt install -y python3-rpi.gpio

printf '%s\n' "==================[3/4] Install fan files"
[[ -f "${SERVICE_SRC}" ]] || { echo "[ERROR] Missing ${SERVICE_SRC}"; exit 1; }
[[ -f "${PY_SRC}" ]] || { echo "[ERROR] Missing ${PY_SRC}"; exit 1; }

# Install fan python script with correct ownership/permissions.
sudo chown "${TARGET_USER}:${TARGET_GROUP}" "${PY_SRC}" || true
sudo chmod 755 "${PY_SRC}" || true

# Install service file and rewrite generic user/home values while installing.
# This avoids hardcoded usernames in the installed unit.
TMP_SERVICE="$(mktemp)"
sed -E \
  -e "s#^([[:space:]]*)User=.*#\\1User=${TARGET_USER}#g" \
  -e "s#^([[:space:]]*)Group=.*#\\1Group=${TARGET_GROUP}#g" \
  -e "s#/home/[^/[:space:]\"']+#${HOME_DIR}#g" \
  "${SERVICE_SRC}" > "${TMP_SERVICE}"

# If the template service has no User=/Group= line, add them under [Service].
if ! grep -qE '^[[:space:]]*User=' "${TMP_SERVICE}"; then
  sed -i "/^\[Service\]/a User=${TARGET_USER}" "${TMP_SERVICE}"
fi

if ! grep -qE '^[[:space:]]*Group=' "${TMP_SERVICE}"; then
  sed -i "/^\[Service\]/a Group=${TARGET_GROUP}" "${TMP_SERVICE}"
fi

sudo install -m 0644 "${TMP_SERVICE}" "${SERVICE_DST}"
rm -f "${TMP_SERVICE}"

printf '%s\n' "==================[4/4] Enable service"
sudo systemctl daemon-reload
sudo systemctl enable --now fan-control.service

echo
printf '%s\n' "================== DONE =================="
echo "Installed: ${SERVICE_DST}"
echo "Check:     systemctl status fan-control.service --no-pager"
echo "NOTE: Reboot once so UART changes fully apply: sudo reboot"
