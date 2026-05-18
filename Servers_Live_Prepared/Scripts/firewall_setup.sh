#!/usr/bin/env bash
set -euo pipefail

# Optional overrides:
#   LAN_CIDR=192.168.1.0/24 bash firewall_setup.sh
#   LAN_IFACE=wlan0 bash firewall_setup.sh
#   FREQ_PORT_RANGE=8010:8040 bash firewall_setup.sh
#   TAILSCALE_IFACE=tailscale0 bash firewall_setup.sh

FREQ_PORT_RANGE="${FREQ_PORT_RANGE:-8010:8040}"
TAILSCALE_IFACE="${TAILSCALE_IFACE:-tailscale0}"

if ! command -v ip >/dev/null 2>&1; then
  echo "[ERROR] Missing required command: ip"
  echo "Install iproute2 first: sudo apt install -y iproute2"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Missing required command: python3"
  echo "Install Python first: sudo apt install -y python3"
  exit 1
fi

echo "==================[1/7] Installing UFW..."
sudo apt update
sudo apt install -y ufw

echo "==================[2/7] Detecting LAN subnet..."

if [[ -z "${LAN_CIDR:-}" ]]; then
  if [[ -z "${LAN_IFACE:-}" ]]; then
    # Pick the default IPv4 route, but do not treat tailscale0 as the LAN interface.
    LAN_IFACE="$(ip -o -4 route show to default | awk -v ts="${TAILSCALE_IFACE}" '$5 != ts {print $5; exit}')"
  fi

  if [[ -z "${LAN_IFACE}" ]]; then
    echo "[ERROR] Could not detect LAN interface."
    echo "Run manually with one of these:"
    echo "  LAN_IFACE=wlan0 bash firewall_setup.sh"
    echo "  LAN_IFACE=eth0 bash firewall_setup.sh"
    echo "  LAN_CIDR=192.168.1.0/24 bash firewall_setup.sh"
    exit 1
  fi

  LAN_ADDR="$(ip -o -4 addr show dev "${LAN_IFACE}" scope global | awk '{print $4; exit}')"

  if [[ -z "${LAN_ADDR}" ]]; then
    echo "[ERROR] Could not detect IPv4 address on interface: ${LAN_IFACE}"
    echo "Run manually with:"
    echo "  LAN_CIDR=192.168.1.0/24 bash firewall_setup.sh"
    exit 1
  fi

  LAN_CIDR="$(python3 - <<PY
import ipaddress
print(ipaddress.ip_interface("${LAN_ADDR}").network)
PY
)"
fi

echo "[INFO] LAN interface: ${LAN_IFACE:-manual}"
echo "[INFO] LAN CIDR: ${LAN_CIDR}"
echo "[INFO] Freqtrade port range: ${FREQ_PORT_RANGE}"
echo "[INFO] Tailscale interface: ${TAILSCALE_IFACE}"

echo "==================[3/7] Resetting firewall..."
sudo ufw --force reset

echo "==================[4/7] Setting default policies..."
sudo ufw default deny incoming
sudo ufw default allow outgoing

echo "==================[5/7] Allowing LAN SSH..."
sudo ufw allow proto tcp from "${LAN_CIDR}" to any port 22

echo "==================[6/7] Allowing LAN Freqtrade range (${FREQ_PORT_RANGE})..."
sudo ufw allow proto tcp from "${LAN_CIDR}" to any port "${FREQ_PORT_RANGE}"

echo "==================[7/7] Allowing Tailscale access..."
sudo ufw allow in on "${TAILSCALE_IFACE}"

echo "[FINAL] Enabling firewall..."
sudo ufw --force enable

echo
echo "================== Firewall status =================="
sudo ufw status verbose
