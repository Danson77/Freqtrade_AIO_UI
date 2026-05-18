#!/usr/bin/env bash
set -e

echo "[1/4] Updating package lists..."
sudo apt update

echo "[2/4] Upgrading system (stable)..."
sudo apt full-upgrade -y

echo "[3/4] Fixing broken packages (if any)..."
sudo apt --fix-broken install -y

echo "[4/4] Cleaning up..."
sudo apt autoremove -y
sudo apt clean

echo "Done. Reboot recommended."