#!/usr/bin/env bash
#
# blurcam installer
# Virtual webcam with AI background blur for Linux ARM64
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/jolehuit/linux-blurcam/main/scripts/install.sh | bash
#

set -e

# ============================================================================
# Colors and formatting
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info() { printf "${BLUE}ℹ${NC} %b\n" "$1"; }
success() { printf "${GREEN}✓${NC} %b\n" "$1"; }
warn() { printf "${YELLOW}⚠${NC} %b\n" "$1"; }
error() { printf "${RED}✗${NC} %b\n" "$1"; }
step() { printf "\n${CYAN}${BOLD}▶ %b${NC}\n" "$1"; }

# Ask yes/no question, returns 0 for yes, 1 for no
ask() {
    local prompt="$1"
    local default="${2:-y}"
    local answer

    if [[ "$default" == "y" ]]; then
        printf "%b ${DIM}[Y/n]${NC} " "$prompt"
    else
        printf "%b ${DIM}[y/N]${NC} " "$prompt"
    fi

    read -r answer
    answer="${answer:-$default}"

    [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]
}

# Run command with sudo
run_sudo() {
    if sudo -n true 2>/dev/null; then
        sudo "$@"
    else
        printf "${DIM}(sudo required)${NC}\n"
        sudo "$@"
    fi
}

# ============================================================================
# System checks
# ============================================================================

check_requirements() {
    # Must not be root
    if [[ "$(id -u)" == "0" ]]; then
        error "Don't run as root. Sudo will be requested when needed."
        exit 1
    fi

    # Must be Linux
    if [[ "$(uname)" != "Linux" ]]; then
        error "This installer only supports Linux."
        exit 1
    fi

    # Check architecture
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  ARCH_PRETTY="x86_64" ;;
        aarch64) ARCH_PRETTY="ARM64" ;;
        *)
            error "Unsupported architecture: $ARCH"
            exit 1
            ;;
    esac

    # Detect distro
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_NAME="${NAME:-Unknown Linux}"
    else
        DISTRO_ID="unknown"
        DISTRO_NAME="Unknown Linux"
    fi

    # Check for Asahi
    IS_ASAHI=false
    uname -r | grep -qi asahi && IS_ASAHI=true

    # Detect package manager
    if command -v dnf &>/dev/null; then
        PKG_MGR="dnf"
    elif command -v apt-get &>/dev/null; then
        PKG_MGR="apt"
    elif command -v pacman &>/dev/null; then
        PKG_MGR="pacman"
    else
        PKG_MGR="unknown"
    fi
}

# ============================================================================
# Installation functions
# ============================================================================

install_uv() {
    step "Checking uv package manager"

    # Check common paths
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v uv &>/dev/null; then
        success "uv is installed ($(uv --version | head -1))"
        return 0
    fi

    info "uv is not installed"
    info "uv is an ultra-fast Python package manager by Astral"
    info "It will also install Python automatically if needed"
    echo

    if ! ask "Install uv?"; then
        error "uv is required to continue."
        exit 1
    fi

    echo
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source the env
    [[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v uv &>/dev/null; then
        success "uv installed ($(uv --version | head -1))"
    else
        error "Failed to install uv. Try restarting your terminal."
        exit 1
    fi
}

install_v4l2loopback() {
    step "Checking v4l2loopback kernel module"

    if modinfo v4l2loopback &>/dev/null; then
        success "v4l2loopback is installed"
        return 0
    fi

    warn "v4l2loopback is not installed"
    info "This kernel module creates the virtual camera device"
    echo

    if ! ask "Install v4l2loopback?"; then
        error "v4l2loopback is required for the virtual camera."
        exit 1
    fi

    echo
    case "$PKG_MGR" in
        dnf)
            if [[ "$IS_ASAHI" == true ]]; then
                info "Asahi Linux detected"
                info "Installing akmod-v4l2loopback + kernel-16k-devel..."
                run_sudo dnf install -y akmod-v4l2loopback
                rpm -q kernel-16k-devel &>/dev/null || run_sudo dnf install -y kernel-16k-devel
                info "Building kernel module (this takes a moment)..."
                run_sudo akmods --force
            else
                info "Installing akmod-v4l2loopback..."
                run_sudo dnf install -y akmod-v4l2loopback
            fi
            ;;
        apt)
            info "Installing v4l2loopback-dkms..."
            run_sudo apt-get update
            run_sudo apt-get install -y v4l2loopback-dkms v4l2loopback-utils
            ;;
        pacman)
            info "Installing v4l2loopback-dkms..."
            # Get kernel headers
            KERNEL=$(pacman -Qqs '^linux[0-9]*$' 2>/dev/null | head -1)
            [[ -n "$KERNEL" ]] && run_sudo pacman -S --noconfirm --needed "${KERNEL}-headers"
            run_sudo pacman -S --noconfirm --needed v4l2loopback-dkms
            ;;
        *)
            error "Unknown package manager."
            info "Please install v4l2loopback manually:"
            info "  Fedora: sudo dnf install akmod-v4l2loopback"
            info "  Ubuntu: sudo apt install v4l2loopback-dkms"
            info "  Arch:   sudo pacman -S v4l2loopback-dkms"
            exit 1
            ;;
    esac

    success "v4l2loopback installed"
}

configure_v4l2loopback() {
    step "Configuring virtual camera"

    # Already configured?
    if [[ -e /dev/video10 ]]; then
        success "Virtual camera ready at /dev/video10"
        return 0
    fi

    info "Setting up /dev/video10..."

    # Persistent config for boot
    if [[ ! -f /etc/modules-load.d/v4l2loopback.conf ]]; then
        echo "v4l2loopback" | run_sudo tee /etc/modules-load.d/v4l2loopback.conf >/dev/null
    fi

    if [[ ! -f /etc/modprobe.d/v4l2loopback.conf ]]; then
        echo 'options v4l2loopback video_nr=10 card_label="BlurCam" exclusive_caps=1' | \
            run_sudo tee /etc/modprobe.d/v4l2loopback.conf >/dev/null
    fi

    # Load now
    run_sudo modprobe -r v4l2loopback 2>/dev/null || true
    run_sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="BlurCam" exclusive_caps=1

    if [[ -e /dev/video10 ]]; then
        success "Virtual camera ready at /dev/video10"
    else
        warn "Could not create /dev/video10 - reboot may be required"
    fi
}

setup_permissions() {
    step "Setting up permissions"

    if groups | grep -qw video; then
        success "User is in 'video' group"
    else
        info "Adding user to 'video' group..."
        run_sudo usermod -aG video "$USER"
        warn "Log out and back in for group changes to take effect"
    fi
}

install_linux_blurcam() {
    step "Installing blurcam"

    # Determine source
    if [[ -f "pyproject.toml" ]] && grep -q "blurcam" pyproject.toml 2>/dev/null; then
        info "Installing from local directory..."
        SOURCE="."
    else
        info "Installing from GitHub..."
        SOURCE="git+https://github.com/jolehuit/linux-blurcam.git"
    fi

    # uv tool install handles everything: Python, deps, etc.
    uv tool install --force "$SOURCE"

    # Verify
    export PATH="$HOME/.local/bin:$PATH"
    if command -v blurcam &>/dev/null; then
        success "blurcam installed ($(blurcam --version 2>/dev/null || echo 'ok'))"
    else
        error "Installation failed. Try: uv tool install $SOURCE"
        exit 1
    fi
}

setup_daemon() {
    step "Setting up background service"

    # Create systemd service
    mkdir -p ~/.config/systemd/user

    cat > ~/.config/systemd/user/blurcam.service << 'EOF'
[Unit]
Description=BlurCam Background Blur Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/blurcam
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable blurcam
    systemctl --user start blurcam

    success "Daemon enabled and started"
}

# ============================================================================
# Main
# ============================================================================

main() {
    clear 2>/dev/null || true

    printf "\n"
    printf "${CYAN}╭──────────────────────────────────────────────────────────╮${NC}\n"
    printf "${CYAN}│${NC}                                                          ${CYAN}│${NC}\n"
    printf "${CYAN}│${NC}   ${BOLD}blurcam${NC}                                          ${CYAN}│${NC}\n"
    printf "${CYAN}│${NC}   ${DIM}Virtual webcam with AI background blur${NC}                 ${CYAN}│${NC}\n"
    printf "${CYAN}│${NC}                                                          ${CYAN}│${NC}\n"
    printf "${CYAN}╰──────────────────────────────────────────────────────────╯${NC}\n"
    printf "\n"

    check_requirements

    info "System: ${BOLD}$DISTRO_NAME${NC} ($ARCH_PRETTY)"
    [[ "$IS_ASAHI" == true ]] && info "        Asahi Linux detected"
    echo

    if ! ask "Start installation?"; then
        info "Cancelled."
        exit 0
    fi

    install_uv
    install_v4l2loopback
    configure_v4l2loopback
    setup_permissions
    install_linux_blurcam
    setup_daemon

    # Done
    printf "\n"
    printf "${GREEN}╭──────────────────────────────────────────────────────────╮${NC}\n"
    printf "${GREEN}│${NC}  ${BOLD}${GREEN}✓ Installation complete!${NC}                                ${GREEN}│${NC}\n"
    printf "${GREEN}╰──────────────────────────────────────────────────────────╯${NC}\n"
    printf "\n"
    printf "  ${BOLD}How to use:${NC}\n"
    printf "\n"
    printf "    Select ${GREEN}'BlurCam'${NC} as your camera in any video app.\n"
    printf "    Blur starts automatically when an app uses it.\n"
    printf "\n"
    printf "  ${BOLD}Adjust blur:${NC}\n"
    printf "    ${CYAN}blurcam config --blur 45${NC}\n"
    printf "\n"

    if ! groups | grep -qw video; then
        printf "  ${YELLOW}⚠ Log out and back in for permissions to take effect${NC}\n\n"
    fi
}

main "$@"
