#!/usr/bin/env bash
set -euo pipefail

echo "==================[1/6] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

echo "==================[2/6] Enabling tailscaled..."
sudo systemctl enable --now tailscaled

echo "==================[3/6] Checking current Tailscale status..."
if tailscale status >/dev/null 2>&1; then
    echo "[INFO] Tailscale appears installed. Continuing..."
fi

sudo tailscale up

echo
echo "Done."
echo "You can now SSH using the Pi's Tailscale IP once your access policy allows it."