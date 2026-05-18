#!/usr/bin/env bash
set -euo pipefail

# Auto-detect target Linux user:
# - Normal run: uses current user
# - Run via sudo: uses SUDO_USER
# - Manual override: FT_USER=someuser bash cleanup_logs.sh
TARGET_USER="${FT_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
    echo "[ERROR] Could not detect a non-root target user."
    echo "Run as a normal user with sudo access, or force it with:"
    echo "  FT_USER=youruser bash cleanup_logs.sh"
    exit 1
fi

HOME_DIR="$(getent passwd "${TARGET_USER}" | cut -d: -f6 || true)"
if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
    echo "[ERROR] Could not detect home directory for user: ${TARGET_USER}"
    exit 1
fi

BASE_DIR="${FREQ_LOG_DIR:-${HOME_DIR}/Servers/Freqtrade/user_data/logs}"

echo "[Cleanup] Target user: ${TARGET_USER}"
echo "[Cleanup] Checking log directory: ${BASE_DIR}"

if [[ ! -d "${BASE_DIR}" ]]; then
    echo "[WARN] Directory not found, nothing to clean: ${BASE_DIR}"
    exit 0
fi

echo "[Cleanup] Deleting freq-*.log older than 7 days..."
find "${BASE_DIR}" -type f -name "freq-*.log" -mtime +7 -print -delete

echo "[Cleanup] Done."
