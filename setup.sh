#!/usr/bin/env bash
# =============================================================================
# AUTOMATED SETUP - REAL-TIME COP-JOINTANGLE-EMG SYSTEM (Raspberry Pi OS / Debian)
#
#   ./setup.sh            install or update (safe to run again)
#   ./setup.sh --clean    delete the Python environment and rebuild it
#   ./setup.sh --yes      do not ask before continuing
#
# What it does:
#   1. apt packages (camera tools, Bluetooth, OpenCV runtime libraries)
#   2. Phidget22 driver from the vendor's signed apt repository
#   3. USB permissions for the PhidgetBridge (udev rule + plugdev group)
#   4. Bluetooth SPP compatibility for the ESP32
#   5. A self-contained Python 3.11 environment in ./venv (Micromamba)
#   6. Runs the diagnostic: python -m acquisition_systems.doctor
#
# Every download is pinned and verified (SHA-256 or GPG fingerprint), so no
# checksum has to be computed by hand. The system Python is never modified.
# =============================================================================

set -euo pipefail

# --- Pinned downloads (update together with their checksums) -----------------
MICROMAMBA_VERSION="2.9.0-0"
MICROMAMBA_SHA256_aarch64="9f93b974adcb4d166996af969b6cd371287d1a3e52733704727884d9b74cb7a7"
MICROMAMBA_SHA256_x86_64="366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3"
PHIDGETS_KEY_URL="https://www.phidgets.com/gpgkey/pubring.gpg"
PHIDGETS_KEY_FINGERPRINT="E5C2AAFCB81F46BE1484A97197833212D4A3B83B"
PYTHON_VERSION="3.11"

# --- Output helpers ------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
step()    { echo -e "\n${BLUE}==> $1${NC}"; }
ok()      { echo -e "${GREEN}    $1${NC}"; }
warn()    { echo -e "${YELLOW}    $1${NC}"; }
fail()    { echo -e "${RED}ERROR: $1${NC}" >&2; exit 1; }

CLEAN=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) fail "unknown option: $arg (use --help)" ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

[ "$(uname -s)" = "Linux" ] || fail "setup.sh is for Linux / Raspberry Pi OS. On Windows run setup.ps1."
command -v apt-get >/dev/null || fail "apt-get not found: this script supports Debian-based systems only."
[ "$(id -u)" -ne 0 ] || fail "run as your normal user (sudo is requested when needed)."

ARCH="$(uname -m)"
case "$ARCH" in
    aarch64|arm64) MM_PLATFORM="linux-aarch64"; MM_SHA256="$MICROMAMBA_SHA256_aarch64" ;;
    x86_64)        MM_PLATFORM="linux-64";      MM_SHA256="$MICROMAMBA_SHA256_x86_64" ;;
    *) fail "unsupported CPU architecture: $ARCH (64-bit OS required)" ;;
esac
. /etc/os-release
CODENAME="${VERSION_CODENAME:-}"

echo -e "${BLUE}REAL-TIME COP-JOINTANGLE-EMG SYSTEM SETUP${NC}"
echo "    System:  ${PRETTY_NAME:-Linux} ($ARCH)"
echo "    Folder:  $REPO_DIR"
if [ "$ASSUME_YES" -ne 1 ] && [ -t 0 ]; then
    echo "    sudo will be used for apt, udev and Bluetooth settings."
    read -r -p "    Continue? [Y/n] " answer
    case "${answer:-y}" in [Yy]*) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

# Ask for the sudo password once and keep the ticket alive while we run.
sudo -v
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
SUDO_KEEPALIVE=$!
TMP_DIR="$(mktemp -d)"
cleanup() { kill "$SUDO_KEEPALIVE" 2>/dev/null || true; rm -rf "$TMP_DIR"; }
trap cleanup EXIT

download() {  # download URL DEST (with retries; the Pi's network can be flaky)
    curl --fail --location --proto '=https' --tlsv1.2 --retry 5 --retry-delay 3 \
         --retry-all-errors --connect-timeout 20 --silent --show-error --output "$2" "$1"
}

# --- 1. System packages -------------------------------------------------------
step "1/6 System packages"
PACKAGES=(curl ca-certificates bzip2 gnupg bluez v4l-utils libgl1 libgomp1 libsm6 libxext6 libxrender1)
# The GLib runtime was renamed (t64 transition) in Debian 13 / Raspberry Pi OS Trixie.
if apt-cache show libglib2.0-0t64 >/dev/null 2>&1; then PACKAGES+=(libglib2.0-0t64); else PACKAGES+=(libglib2.0-0); fi
# CSI cameras (Rpi P5V04A V1.3) are reached through libcamera's rpicam-vid.
if apt-cache show rpicam-apps >/dev/null 2>&1; then PACKAGES+=(rpicam-apps); fi
MISSING=()
for pkg in "${PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || MISSING+=("$pkg")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}"
    ok "installed: ${MISSING[*]}"
else
    ok "all packages already installed"
fi

# --- 2. Phidget22 driver (signed vendor repository) --------------------------
step "2/6 Phidget22 driver"
if dpkg-query -W -f='${Status}' libphidget22 2>/dev/null | grep -q "install ok installed"; then
    ok "libphidget22 already installed ($(dpkg-query -W -f='${Version}' libphidget22))"
else
    [ -n "$CODENAME" ] || fail "cannot detect the Debian codename for the Phidgets repository"
    download "$PHIDGETS_KEY_URL" "$TMP_DIR/phidgets.key"
    gpg --dearmor --yes --output "$TMP_DIR/phidgets.gpg" "$TMP_DIR/phidgets.key" 2>/dev/null \
        || cp "$TMP_DIR/phidgets.key" "$TMP_DIR/phidgets.gpg"
    FPR="$(gpg --show-keys --with-colons "$TMP_DIR/phidgets.gpg" 2>/dev/null | awk -F: '/^fpr/ {print $10; exit}')"
    [ "$FPR" = "$PHIDGETS_KEY_FINGERPRINT" ] || fail "Phidgets signing key fingerprint mismatch (got '$FPR')"
    sudo install -m 0644 "$TMP_DIR/phidgets.gpg" /usr/share/keyrings/phidgets.gpg
    DEB_ARCH="$(dpkg --print-architecture)"
    echo "deb [arch=$DEB_ARCH signed-by=/usr/share/keyrings/phidgets.gpg] https://www.phidgets.com/debian $CODENAME main" \
        | sudo tee /etc/apt/sources.list.d/phidgets.list >/dev/null
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libphidget22
    ok "libphidget22 installed from the signed Phidgets repository"
fi

# --- 3. USB permissions for the PhidgetBridge --------------------------------
step "3/6 USB permissions (PhidgetBridge)"
UDEV_RULE='SUBSYSTEMS=="usb", ACTION=="add", ATTRS{idVendor}=="06c2", ATTRS{idProduct}=="00[3-a][0-f]", GROUP="plugdev", MODE="0660"'
UDEV_FILE=/etc/udev/rules.d/99-libphidget22.rules
if [ "$(cat "$UDEV_FILE" 2>/dev/null)" != "$UDEV_RULE" ]; then
    echo "$UDEV_RULE" | sudo tee "$UDEV_FILE" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=usb
    ok "udev rule written ($UDEV_FILE)"
else
    ok "udev rule already present"
fi
NEED_RELOGIN=0
for group in plugdev dialout video; do
    getent group "$group" >/dev/null || sudo groupadd --force "$group"
    if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$group"; then
        sudo usermod -aG "$group" "$USER"
        NEED_RELOGIN=1
        ok "added $USER to group $group"
    fi
done
[ "$NEED_RELOGIN" -eq 1 ] || ok "$USER already in plugdev, dialout and video"

# --- 4. Bluetooth Classic SPP (ESP32) -----------------------------------------
step "4/6 Bluetooth SPP for the ESP32"
BLUETOOTHD="$(command -v bluetoothd || true)"
for candidate in /usr/libexec/bluetooth/bluetoothd /usr/lib/bluetooth/bluetoothd; do
    [ -x "$candidate" ] && BLUETOOTHD="$candidate" && break
done
OVERRIDE_FILE=/etc/systemd/system/bluetooth.service.d/compat.conf
OVERRIDE="$(printf '[Service]\nExecStart=\nExecStart=%s --compat\n' "$BLUETOOTHD")"
if [ -z "$BLUETOOTHD" ]; then
    warn "bluetoothd not found; skipping (EMG will use the simulator)"
elif [ "$(cat "$OVERRIDE_FILE" 2>/dev/null)" != "$OVERRIDE" ]; then
    sudo mkdir -p "$(dirname "$OVERRIDE_FILE")"
    echo "$OVERRIDE" | sudo tee "$OVERRIDE_FILE" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl restart bluetooth
    ok "bluetoothd runs with --compat (RFCOMM/SPP enabled)"
else
    ok "SPP compatibility already enabled"
fi

# --- 5. Python environment ------------------------------------------------------
step "5/6 Python $PYTHON_VERSION environment (./venv)"
MAMBA="$REPO_DIR/bin/micromamba"
if [ ! -x "$MAMBA" ] || ! "$MAMBA" --version 2>/dev/null | grep -q "^${MICROMAMBA_VERSION%-*}"; then
    mkdir -p "$REPO_DIR/bin"
    download "https://github.com/mamba-org/micromamba-releases/releases/download/$MICROMAMBA_VERSION/micromamba-$MM_PLATFORM" \
        "$TMP_DIR/micromamba"
    echo "$MM_SHA256  $TMP_DIR/micromamba" | sha256sum --check --status \
        || fail "Micromamba checksum mismatch (download corrupted or tampered)"
    install -m 0755 "$TMP_DIR/micromamba" "$MAMBA"
    ok "Micromamba $MICROMAMBA_VERSION verified and installed in ./bin"
fi
export MAMBA_ROOT_PREFIX="$REPO_DIR/.mamba_root"

if [ "$CLEAN" -eq 1 ] && [ -d venv ]; then
    warn "--clean: removing the existing ./venv"
    rm -rf venv
fi
if [ ! -x venv/bin/python ] || ! venv/bin/python -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>/dev/null; then
    rm -rf venv
    # Qt and Tk come from conda-forge: their aarch64 pip wheels are missing or
    # lack the X11/XWayland platform plugins on Raspberry Pi OS.
    "$MAMBA" create -y -q -p ./venv -c conda-forge "python=$PYTHON_VERSION" tk pyqt=5 pyqtgraph >/dev/null
    ok "environment created"
else
    ok "environment already exists (use --clean to rebuild)"
fi
venv/bin/python -m pip install -q --upgrade pip
venv/bin/python -m pip install -q -r requirements.txt
ok "Python dependencies installed from requirements.txt"

# --- 6. Diagnostic -------------------------------------------------------------
step "6/6 Diagnostic"
set +e
venv/bin/python -m acquisition_systems.doctor
DOCTOR_STATUS=$?
set -e

echo
if [ "$DOCTOR_STATUS" -eq 0 ]; then
    echo -e "${GREEN}SETUP COMPLETED${NC}"
else
    echo -e "${YELLOW}SETUP COMPLETED, but the diagnostic reported errors (see above).${NC}"
fi
if [ "$NEED_RELOGIN" -eq 1 ]; then
    warn "Log out and back in (or reboot) so the new group membership applies to the force plate."
fi
echo "    Run the application:  ./venv/bin/python -m acquisition_systems.app_gui"
echo "    Re-check hardware:    ./venv/bin/python -m acquisition_systems.doctor"
exit "$DOCTOR_STATUS"
