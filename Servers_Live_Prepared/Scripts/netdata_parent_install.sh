#!/usr/bin/env bash
set -euo pipefail

NETDATA_PORT_DEFAULT="19999"

echo "==================[1/5] Base packages"
sudo apt update
sudo apt install -y ca-certificates curl gnupg uuid-runtime

echo "==================[2/5] Detect Tailscale IP"
TS_IP="$(tailscale ip -4 | head -n1 || true)"
if [[ -z "${TS_IP}" ]]; then
  echo "[ERROR] Could not detect Tailscale IPv4. Make sure Tailscale is connected."
  exit 1
fi
echo "[INFO] Tailscale IP: ${TS_IP}"

echo "==================[3/5] Install or switch Netdata to stable"
if [[ ! -x /opt/netdata/bin/srv/netdata ]]; then
  curl -fsSL https://get.netdata.cloud/kickstart.sh | sudo bash -s -- \
    --install-type static \
    --release-channel stable \
    --dont-wait \
    --disable-telemetry
else
  echo "[INFO] Netdata already installed at /opt/netdata. Reinstalling on stable channel..."
  curl -fsSL https://get.netdata.cloud/kickstart.sh | sudo bash -s -- \
    --install-type static \
    --release-channel stable \
    --dont-wait \
    --disable-telemetry \
    --reinstall
fi

echo "==================[4/5] Configure as Netdata PARENT"
read -rp "Enter Netdata stream API key (leave blank to auto-generate): " API_KEY
if [[ -z "${API_KEY}" ]]; then
  API_KEY="$(uuidgen)"
  echo "[INFO] Generated API key:"
  echo "  ${API_KEY}"
fi

read -rp "Enter parent listen port [${NETDATA_PORT_DEFAULT}]: " NETDATA_PORT
NETDATA_PORT="${NETDATA_PORT:-${NETDATA_PORT_DEFAULT}}"

sudo mkdir -p /opt/netdata/etc/netdata

sudo tee /opt/netdata/etc/netdata/netdata.conf >/dev/null <<EOF
[web]
    bind to = 127.0.0.1:${NETDATA_PORT} ${TS_IP}:${NETDATA_PORT}
EOF

sudo tee /opt/netdata/etc/netdata/stream.conf >/dev/null <<EOF
[stream]
    enabled = no

[${API_KEY}]
    enabled = yes
EOF

echo "==================[5/5] Restart Netdata + verify"
sudo systemctl restart netdata
sleep 2

echo
echo "================== Parent ready"
echo "Tailscale IP: ${TS_IP}"
echo "Port:         ${NETDATA_PORT}"
echo "API key:      ${API_KEY}"
echo
echo "Children should use:"
echo "  parent host/ip = ${TS_IP}"
echo "  port           = ${NETDATA_PORT}"
echo "  api key        = ${API_KEY}"
echo
echo "Checks:"
echo "  curl -s http://127.0.0.1:${NETDATA_PORT}/api/v1/info | grep version"
echo "  ss -tulpen | grep ${NETDATA_PORT}"