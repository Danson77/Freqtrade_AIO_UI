#!/usr/bin/env bash
set -euo pipefail

# =======================
# SETTINGS
# =======================
ZRAM_ALGO="zstd"
ZRAM_PERCENT="80"
ZRAM_PRIORITY="100"

SWAPFILE="/swapfile"
SWAP_SIZE="3G"
SWAP_PRI="10"

echo "==================[0/6] Stop anything that might auto-create /dev/zram0"

# Pi OS newer swap stack
sudo systemctl stop dev-zram0.swap 2>/dev/null || true
sudo systemctl disable dev-zram0.swap 2>/dev/null || true
sudo systemctl mask dev-zram0.swap 2>/dev/null || true

sudo systemctl disable --now rpi-zram-writeback.service 2>/dev/null || true
sudo systemctl disable --now rpi-zram-writeback.timer 2>/dev/null || true
sudo systemctl mask rpi-zram-writeback.service 2>/dev/null || true
sudo systemctl mask rpi-zram-writeback.timer 2>/dev/null || true

# Old Pi OS swap manager
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true
sudo systemctl mask dphys-swapfile 2>/dev/null || true
sudo apt purge -y dphys-swapfile 2>/dev/null || true

echo "==================[1/6] Stop zramswap + turn off all swap"
sudo systemctl stop zramswap.service 2>/dev/null || true
sudo systemctl disable zramswap.service 2>/dev/null || true
sudo swapoff -a 2>/dev/null || true

echo "==================[2/6] Fully clean zram state"
if [ -e /sys/block/zram0/reset ]; then
    echo 1 | sudo tee /sys/block/zram0/reset >/dev/null || true
fi

sudo modprobe -r zram 2>/dev/null || true
sleep 1
sudo modprobe zram

echo "==================[3/6] Install zram-tools + configure"
sudo apt update
sudo apt install -y zram-tools

sudo tee /etc/default/zramswap >/dev/null <<EOF
ALGO=${ZRAM_ALGO}
PERCENT=${ZRAM_PERCENT}
SIZE=0
PRIORITY=${ZRAM_PRIORITY}
EOF

echo "==================[4/6] Enable zram-tools swap"
sudo systemctl daemon-reload
sudo systemctl enable zramswap.service
sudo systemctl restart zramswap.service

echo "==================[5/6] Recreate swapfile ${SWAPFILE} (${SWAP_SIZE}) cleanly"
sudo swapoff "${SWAPFILE}" 2>/dev/null || true
sudo rm -f "${SWAPFILE}"

sudo fallocate -l "${SWAP_SIZE}" "${SWAPFILE}"
sudo chmod 600 "${SWAPFILE}"
sudo mkswap "${SWAPFILE}"
sudo swapon --priority "${SWAP_PRI}" "${SWAPFILE}"

echo "==================[6/6] Fix /etc/fstab entry"
sudo cp /etc/fstab /etc/fstab.bak.$(date +%F_%H%M%S)
sudo sed -i '\|^\s*/swapfile\s\+none\s\+swap\s|d' /etc/fstab
sudo sed -i '\|^\s*/var/swap\s\+none\s\+swap\s|d' /etc/fstab
sudo sed -i '\|^\s*/swap\s\+none\s\+swap\s|d' /etc/fstab
echo "${SWAPFILE} none swap sw,pri=${SWAP_PRI} 0 0" | sudo tee -a /etc/fstab >/dev/null
echo "DONE ✅ zram priority=${ZRAM_PRIORITY}, swapfile priority=${SWAP_PRI}"