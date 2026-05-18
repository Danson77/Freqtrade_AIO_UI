#!/usr/bin/env bash
set -euo pipefail

# Auto-detect target Linux user:
# - Normal run: uses current user
# - Run via sudo: uses SUDO_USER
# - Manual override: FT_USER=someuser bash main.sh
TARGET_USER="${FT_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
    echo "[ERROR] Could not detect a non-root target user."
    echo "Run as a normal user with sudo access, or force it with:"
    echo "  FT_USER=youruser bash main.sh"
    exit 1
fi

TARGET_GROUP="$(id -gn "${TARGET_USER}")"
HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6 || true)"

if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
    echo "[ERROR] Could not detect home directory for user: ${TARGET_USER}"
    exit 1
fi

# The script source folder defaults to the folder where main.sh is located.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE_DIR="${SOURCE_DIR:-${SCRIPT_DIR}}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pi-maintenance}"
SERVERS_DIR="${SERVERS_DIR:-${HOME_DIR}/Servers}"

CLEANUP_SCRIPT="cleanup_logs.sh"
UPDATE_SCRIPT="deb_update.sh"

# Pass the detected user to child scripts.
export FT_USER="${TARGET_USER}"

echo "================== Target user =================="
echo "User:        ${TARGET_USER}"
echo "Group:       ${TARGET_GROUP}"
echo "Home:        ${HOME_DIR}"
echo "Source dir:  ${SOURCE_DIR}"
echo "Servers dir: ${SERVERS_DIR}"
echo

# ===== PRECHECK =====
echo "[1/16] Making all .sh scripts in source executable..."
find "${SOURCE_DIR}" -maxdepth 1 -type f -name "*.sh" -exec chmod +x {} \;

echo "[2/16] Making start-*.sh scripts in Servers executable..."
mkdir -p "${SERVERS_DIR}"
sudo chown "${TARGET_USER}:${TARGET_GROUP}" "${SERVERS_DIR}" || true
find "${SERVERS_DIR}" -maxdepth 1 -type f -name "start-*.sh" -exec chmod +x {} \;

echo "[3/16] Checking required scripts..."
if [[ ! -f "${SOURCE_DIR}/${CLEANUP_SCRIPT}" ]]; then
    echo "[ERROR] Missing: ${SOURCE_DIR}/${CLEANUP_SCRIPT}"
    exit 1
fi

if [[ ! -f "${SOURCE_DIR}/${UPDATE_SCRIPT}" ]]; then
    echo "[ERROR] Missing: ${SOURCE_DIR}/${UPDATE_SCRIPT}"
    exit 1
fi

# ===== INSTALL DIR =====
echo "[4/16] Creating install directory..."
sudo mkdir -p "${INSTALL_DIR}"

echo "[5/16] Copying maintenance scripts..."
sudo cp "${SOURCE_DIR}/${CLEANUP_SCRIPT}" "${INSTALL_DIR}/${CLEANUP_SCRIPT}"
sudo cp "${SOURCE_DIR}/${UPDATE_SCRIPT}" "${INSTALL_DIR}/${UPDATE_SCRIPT}"

echo "[6/16] Setting ownership and permissions..."
sudo chown root:root "${INSTALL_DIR}/${CLEANUP_SCRIPT}" "${INSTALL_DIR}/${UPDATE_SCRIPT}"
sudo chmod 755 "${INSTALL_DIR}/${CLEANUP_SCRIPT}" "${INSTALL_DIR}/${UPDATE_SCRIPT}"

# ===== CLEANUP SERVICE =====
echo "[7/16] Creating cleanup service + timer..."
sudo tee /etc/systemd/system/cleanup-logs.service > /dev/null <<EOF
[Unit]
Description=Cleanup old Freqtrade logs

[Service]
Type=oneshot
User=${TARGET_USER}
Environment=FT_USER=${TARGET_USER}
ExecStart=${INSTALL_DIR}/${CLEANUP_SCRIPT}
EOF

sudo tee /etc/systemd/system/cleanup-logs.timer > /dev/null <<EOF
[Unit]
Description=Run cleanup logs every 7 days

[Timer]
OnBootSec=10min
OnUnitActiveSec=7d
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
EOF

# ===== UPDATE SERVICE =====
echo "[8/16] Creating update service + timer..."
sudo tee /etc/systemd/system/deb-update.service > /dev/null <<EOF
[Unit]
Description=Weekly Debian package update

[Service]
Type=oneshot
ExecStart=${INSTALL_DIR}/${UPDATE_SCRIPT}
EOF

sudo tee /etc/systemd/system/deb-update.timer > /dev/null <<EOF
[Unit]
Description=Run Debian update every 7 days

[Timer]
OnBootSec=30min
OnUnitActiveSec=7d
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
EOF

echo "[9/16] Reloading systemd and enabling timers..."
sudo systemctl daemon-reload
sudo systemctl enable --now cleanup-logs.timer
sudo systemctl enable --now deb-update.timer

echo
echo "[10/16] Running fan installer..."
bash "${SOURCE_DIR}/fan_install.sh"

echo
echo "[11/16] Running Tailscale installer..."
bash "${SOURCE_DIR}/tail_install.sh"

echo
echo "[12/16] Running firewall installer..."
bash "${SOURCE_DIR}/firewall_setup.sh"

echo
echo "[13/16] Running ZRAM installer..."
bash "${SOURCE_DIR}/zram_install.sh"

echo
echo "[14/16] Running stats/Netdata child installer..."
bash "${SOURCE_DIR}/stats_install.sh"

echo
echo "[15/16] Running Freqtrade installer..."
bash "${SOURCE_DIR}/freq_install.sh"

echo
echo "[16/16] Running Freqtrade services installer..."
bash "${SOURCE_DIR}/freq_services.sh"

echo
echo "================================================================================="
echo
echo "================== Showing assigned Tailscale IP =================="
tailscale ip -4 || true

echo
echo "================== Tailscale status =================="
tailscale status || true

echo
echo "================== Firewall active =================="
sudo ufw status verbose || true

echo
echo "================== ZRAM Verify =================="
echo
echo "--- active swap devices ---"
sudo swapon --show || true
echo
echo "--- /proc/swaps ---"
cat /proc/swaps || true
echo
echo "--- zramctl ---"
command -v zramctl >/dev/null && zramctl || true

echo
echo "================== Child ready =================="
echo
echo "Netdata service:"
systemctl is-active netdata && echo "✅ netdata active" || echo "❌ netdata not active"

echo
echo "Netdata process:"
ps aux | grep '[n]etdata' || true

echo
echo "Config files:"
ls -l /opt/netdata/etc/netdata/netdata.conf /opt/netdata/etc/netdata/stream.conf 2>/dev/null || true
ls -l /etc/netdata/netdata.conf /etc/netdata/stream.conf 2>/dev/null || true

echo
echo "Check logs with:"
echo "  journalctl -u netdata -n 100 --no-pager"

echo
echo "Check child stream logs with:"
echo "  journalctl -r --namespace=netdata MESSAGE_ID=6e2e3839067648968b646045dbf28d66 --no-pager"

echo
echo "--- Check timers with ---"
echo "  systemctl list-timers --all"

echo
echo "--- Test manually with ---"
echo "  sudo systemctl start cleanup-logs.service"
echo "  sudo systemctl start deb-update.service"

echo
echo "--- zramswap.service ---"
echo "  sudo systemctl status zramswap.service --no-pager"

echo
echo "--- Service status of fan ---"
echo "  systemctl status fan-control.service --no-pager"

echo
echo "DONE."
