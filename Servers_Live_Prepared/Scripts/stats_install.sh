#!/usr/bin/env bash
set -euo pipefail

NETDATA_PORT_DEFAULT="19999"

echo "==================[1/8] Base packages"
sudo apt update
sudo apt install -y ca-certificates curl gnupg

echo "==================[2/8] Add Tailscale APT repo (Debian/RPi OS)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
if [[ -z "${CODENAME}" ]]; then
  echo "[ERROR] Could not detect VERSION_CODENAME from /etc/os-release"
  exit 1
fi
echo "Detected codename: ${CODENAME}"

sudo install -d -m 0755 /usr/share/keyrings /etc/apt/sources.list.d

curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.noarmor.gpg" \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null

curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.tailscale-keyring.list" \
  | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null

echo "==================[3/8] Install Tailscale"
sudo apt update
sudo apt install -y tailscale

echo "==================[4/8] Enable Tailscale daemon"
sudo systemctl enable --now tailscaled

echo "==================[5/8] Join Tailscale if needed"
if tailscale status >/dev/null 2>&1; then
  echo "[INFO] Tailscale already connected."
else
  sudo tailscale up
fi

echo "==================[6/8] Collect parent info"
read -rp "Enter Netdata parent Tailscale IP or hostname: " PARENT_HOST
if [[ -z "${PARENT_HOST}" ]]; then
  echo "[ERROR] Parent host/IP is required."
  exit 1
fi

read -rp "Enter Netdata stream API key: " API_KEY
if [[ -z "${API_KEY}" ]]; then
  echo "[ERROR] API key is required."
  exit 1
fi

read -rp "Enter Netdata parent port [${NETDATA_PORT_DEFAULT}]: " NETDATA_PORT
NETDATA_PORT="${NETDATA_PORT:-${NETDATA_PORT_DEFAULT}}"

echo "==================[7/8] Install Netdata + configure as CHILD"
curl -fsSL https://get.netdata.cloud/kickstart.sh | sudo bash -s -- \
  --install-type static \
  --dont-wait \
  --disable-telemetry \
  --disable-cloud

sudo mkdir -p /opt/netdata/etc/netdata
sudo mkdir -p /etc/netdata

# Disable local dashboard on child nodes
sudo tee /opt/netdata/etc/netdata/netdata.conf >/dev/null <<'EOF'
[web]
    mode = none
EOF

sudo tee /etc/netdata/netdata.conf >/dev/null <<'EOF'
[web]
    mode = none
EOF

# Stream to parent
sudo tee /opt/netdata/etc/netdata/stream.conf >/dev/null <<EOF
[stream]
    enabled = yes
    destination = ${PARENT_HOST}:${NETDATA_PORT}
    api key = ${API_KEY}
EOF

sudo tee /etc/netdata/stream.conf >/dev/null <<EOF
[stream]
    enabled = yes
    destination = ${PARENT_HOST}:${NETDATA_PORT}
    api key = ${API_KEY}
EOF

echo "==================[8/8] Restart Netdata + verify"
sudo systemctl restart netdata
sleep 2