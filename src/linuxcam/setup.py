#!/usr/bin/env python3
"""
blurcam-setup - Check and configure system dependencies for blurcam

Detects your Linux distribution and provides appropriate installation commands.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def detect_distro() -> dict:
    """Detect the Linux distribution."""
    distro = {"id": "unknown", "name": "Unknown", "family": "unknown"}

    # Try os-release first
    os_release = Path("/etc/os-release")
    if os_release.exists():
        content = os_release.read_text()
        for line in content.splitlines():
            if line.startswith("ID="):
                distro["id"] = line.split("=")[1].strip().strip('"').lower()
            elif line.startswith("NAME="):
                distro["name"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("ID_LIKE="):
                distro["family"] = line.split("=")[1].strip().strip('"').lower()

    # Determine package manager family
    if distro["id"] in ("fedora", "rhel", "centos", "rocky", "alma"):
        distro["family"] = "fedora"
        distro["pkg_manager"] = "dnf"
    elif distro["id"] in ("debian", "ubuntu", "linuxmint", "pop", "raspbian"):
        distro["family"] = "debian"
        distro["pkg_manager"] = "apt"
    elif distro["id"] in ("arch", "manjaro", "endeavouros"):
        distro["family"] = "arch"
        distro["pkg_manager"] = "pacman"
    elif "fedora" in distro.get("family", ""):
        distro["family"] = "fedora"
        distro["pkg_manager"] = "dnf"
    elif "debian" in distro.get("family", "") or "ubuntu" in distro.get("family", ""):
        distro["family"] = "debian"
        distro["pkg_manager"] = "apt"
    elif "arch" in distro.get("family", ""):
        distro["family"] = "arch"
        distro["pkg_manager"] = "pacman"

    # Check for Asahi Linux
    uname = run_cmd(["uname", "-r"])
    if "asahi" in uname.stdout.lower():
        distro["is_asahi"] = True
    else:
        distro["is_asahi"] = False

    return distro


def check_v4l2loopback() -> dict:
    """Check v4l2loopback module status."""
    result = {"installed": False, "loaded": False, "device": None}

    # Check if module is available
    modinfo = run_cmd(["modinfo", "v4l2loopback"])
    result["installed"] = modinfo.returncode == 0

    # Check if module is loaded
    lsmod = run_cmd(["lsmod"])
    result["loaded"] = "v4l2loopback" in lsmod.stdout

    # Find virtual camera device
    for i in range(20):
        dev = f"/dev/video{i}"
        if os.path.exists(dev):
            # Check if it's a v4l2loopback device
            try:
                name_path = f"/sys/devices/virtual/video4linux/video{i}/name"
                if os.path.exists(name_path):
                    with open(name_path) as f:
                        name = f.read().strip()
                        if "loopback" in name.lower() or "virtual" in name.lower():
                            result["device"] = dev
                            result["device_name"] = name
                            break
            except:
                pass

    return result


def get_install_instructions(distro: dict) -> str:
    """Get installation instructions for the detected distro."""
    instructions = []

    if distro["family"] == "fedora":
        if distro["is_asahi"]:
            instructions.append("# Asahi Linux (Fedora-based)")
            instructions.append("sudo dnf install akmod-v4l2loopback")
            instructions.append("sudo dnf install kernel-16k-devel  # For Asahi kernel")
            instructions.append("sudo akmods --force")
        else:
            instructions.append("# Fedora")
            instructions.append("sudo dnf install akmod-v4l2loopback")

    elif distro["family"] == "debian":
        instructions.append("# Debian/Ubuntu/Raspberry Pi OS")
        instructions.append("sudo apt update")
        instructions.append("sudo apt install v4l2loopback-dkms v4l2loopback-utils")

    elif distro["family"] == "arch":
        instructions.append("# Arch Linux / Manjaro")
        instructions.append("sudo pacman -S v4l2loopback-dkms")

    else:
        instructions.append("# Unknown distribution - try one of:")
        instructions.append("# Fedora: sudo dnf install akmod-v4l2loopback")
        instructions.append("# Debian: sudo apt install v4l2loopback-dkms")
        instructions.append("# Arch: sudo pacman -S v4l2loopback-dkms")

    return "\n".join(instructions)


def get_modprobe_command(device_nr: int = 10) -> str:
    """Get the modprobe command to load v4l2loopback."""
    return f'sudo modprobe v4l2loopback devices=1 video_nr={device_nr} card_label="BlurCam" exclusive_caps=1'


def print_status(label: str, ok: bool, detail: str = ""):
    """Print a status line."""
    status = "\033[92m✓\033[0m" if ok else "\033[91m✗\033[0m"
    print(f"  {status} {label}", end="")
    if detail:
        print(f" ({detail})", end="")
    print()


def main():
    print()
    print("=" * 60)
    print("  blurcam System Setup Check")
    print("=" * 60)
    print()

    # Detect distribution
    distro = detect_distro()
    print(f"Distribution: {distro['name']}")
    if distro["is_asahi"]:
        print("             (Asahi Linux detected)")
    print()

    # Check v4l2loopback
    print("Checking v4l2loopback:")
    v4l2 = check_v4l2loopback()

    print_status("Module installed", v4l2["installed"])
    print_status("Module loaded", v4l2["loaded"])
    print_status(
        "Virtual camera device",
        v4l2["device"] is not None,
        v4l2.get("device", "not found"),
    )
    print()

    # Provide instructions if needed
    if not v4l2["installed"]:
        print("v4l2loopback is not installed. Install it with:")
        print()
        print(get_install_instructions(distro))
        print()

    elif not v4l2["loaded"]:
        print("v4l2loopback is installed but not loaded. Load it with:")
        print()
        print(get_modprobe_command())
        print()
        print("To load automatically at boot, create /etc/modules-load.d/v4l2loopback.conf:")
        print()
        print('  echo "v4l2loopback" | sudo tee /etc/modules-load.d/v4l2loopback.conf')
        print()
        print("And configure options in /etc/modprobe.d/v4l2loopback.conf:")
        print()
        print(
            '  echo \'options v4l2loopback video_nr=10 card_label="BlurCam" exclusive_caps=1\' | sudo tee /etc/modprobe.d/v4l2loopback.conf'
        )
        print()

    elif v4l2["device"] is None:
        print("Module is loaded but no virtual camera device found.")
        print("Try reloading with correct options:")
        print()
        print("  sudo modprobe -r v4l2loopback")
        print(get_modprobe_command())
        print()

    else:
        print("\033[92mAll good! You can now run:\033[0m")
        print()
        print(f"  blurcam")
        print()

    return 0 if (v4l2["installed"] and v4l2["loaded"] and v4l2["device"]) else 1


if __name__ == "__main__":
    sys.exit(main())
