#!/usr/bin/env bash
set -euo pipefail

SOCKET_DIR="${SOCKET_DIR:-/tmp/ch_sockets}"
LEAKS_FOUND=0

echo "=========================================================="
echo "          PS-023 ZERO-LEAK RESIDUAL AUDIT"
echo "=========================================================="

echo -n "[*] Checking for lingering cloud-hypervisor processes... "
if pgrep -f "cloud-hypervisor" > /dev/null 2>&1; then
    echo "FAILED"
    echo "[!] Active cloud-hypervisor processes found:"
    pgrep -a -f "cloud-hypervisor" || true
    LEAKS_FOUND=1
else
    echo "CLEAN (0 active processes)"
fi

echo -n "[*] Checking for orphaned UNIX domain sockets in ${SOCKET_DIR}... "
if [ -d "$SOCKET_DIR" ]; then
    SOCKET_COUNT=$(find "$SOCKET_DIR" -maxdepth 1 -name "*.sock" | wc -l)
    if [ "$SOCKET_COUNT" -gt 0 ]; then
        echo "FAILED ($SOCKET_COUNT dangling sockets detected)"
        find "$SOCKET_DIR" -maxdepth 1 -name "*.sock"
        LEAKS_FOUND=1
    else
        echo "CLEAN (0 dangling sockets)"
    fi
else
    echo "CLEAN (Directory does not exist)"
fi

echo "----------------------------------------------------------"
if [ "$LEAKS_FOUND" -eq 0 ]; then
    echo "[SUCCESS] Zero resource leaks detected. Environment is pristine."
    exit 0
else
    echo "[ERROR] Resource leaks detected! Review output above."
    exit 1
fi
