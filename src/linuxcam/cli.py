#!/usr/bin/env python3
"""
blurcam - Virtual webcam with AI background blur for Linux ARM64

Usage:
    blurcam                    Run the daemon (auto-detects when apps use BlurCam)
    blurcam config             Show current settings
    blurcam config --blur 45   Adjust blur strength (live)
    blurcam uninstall          Remove blurcam completely
"""

import argparse
import os
import sys
import time

from . import __version__
from .config import load_config, update_config, get_config_mtime, DEFAULT_CONFIG


def cmd_uninstall(args):
    """Uninstall blurcam completely."""
    import shutil
    import subprocess
    from pathlib import Path

    print("Uninstalling blurcam...\n")

    # 1. Stop and disable systemd service
    print("Stopping service...")
    subprocess.run(
        ["systemctl", "--user", "stop", "blurcam"],
        capture_output=True
    )
    subprocess.run(
        ["systemctl", "--user", "disable", "blurcam"],
        capture_output=True
    )

    # 2. Remove systemd service file
    print("Removing systemd service...")
    service_file = Path.home() / ".config/systemd/user/blurcam.service"
    if service_file.exists():
        service_file.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)

    # 3. Remove config files
    print("Removing config files...")
    config_dir = Path.home() / ".config/blurcam"
    if config_dir.exists():
        shutil.rmtree(config_dir)

    # 4. Remove cached model
    print("Removing cached model...")
    cache_dir = Path.home() / ".cache/blurcam"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    # 5. Remove uv tool environment (onnx, opencv, etc.)
    print("Removing Python environment...")
    uv_tool_dir = Path.home() / ".local/share/uv/tools/blurcam"
    if uv_tool_dir.exists():
        shutil.rmtree(uv_tool_dir)

    # 6. Remove shell aliases
    print("Removing shell aliases...")
    for rc_name in [".bashrc", ".zshrc"]:
        rc_file = Path.home() / rc_name
        if rc_file.exists():
            content = rc_file.read_text()
            # Remove the alias block
            import re
            new_content = re.sub(
                r'\n# blurcam shortcuts\n.*?alias noblur=.*?\n',
                '\n',
                content,
                flags=re.DOTALL
            )
            if new_content != content:
                rc_file.write_text(new_content)

    # 7. Remove v4l2loopback config (requires sudo)
    print("Removing v4l2loopback config...")
    v4l_configs = [
        Path("/etc/modprobe.d/v4l2loopback.conf"),
        Path("/etc/modules-load.d/v4l2loopback.conf"),
    ]
    for conf in v4l_configs:
        if conf.exists():
            result = subprocess.run(
                ["sudo", "rm", "-f", str(conf)],
                capture_output=True
            )
            if result.returncode != 0:
                print(f"  Run manually: sudo rm {conf}")

    # 8. Uninstall the tool itself via uv
    print("Removing blurcam...")
    subprocess.run(
        ["uv", "tool", "uninstall", "blurcam"],
        capture_output=True
    )

    print("\n✓ blurcam uninstalled!\n")
    return 0


def cmd_config(args):
    """Handle config subcommand."""
    # If any setting provided, update config
    if args.blur is not None or args.threshold is not None:
        updates = {}
        if args.blur is not None:
            # Ensure blur is odd
            blur = args.blur if args.blur % 2 == 1 else args.blur + 1
            updates["blur"] = blur
        if args.threshold is not None:
            updates["threshold"] = args.threshold

        config = update_config(**updates)
        print(f"Settings updated:")
        if args.blur is not None:
            print(f"  blur: {config['blur']}")
        if args.threshold is not None:
            print(f"  threshold: {config['threshold']}")
        print()
        print("Changes apply immediately to running instance.")
        return 0

    # Otherwise show current config
    config = load_config()
    print("Current settings:")
    print(f"  blur: {config['blur']}")
    print()
    print("Adjust with:")
    print("  blurcam config --blur 45")
    print()
    print("Advanced:")
    print(f"  threshold: {config['threshold']} (detection sensitivity, 0-1)")
    return 0


def cmd_run(args):
    """Run the virtual camera."""
    # Lazy imports to avoid ONNX warnings on --help
    import cv2
    import numpy as np
    import pyvirtualcam
    from .models import get_model_path
    from .segmentation import SelfieSegmentation, apply_background_blur
    from .config import get_config_path

    # Load config
    config = load_config()

    # CLI args override config
    if args.blur is not None:
        config["blur"] = args.blur if args.blur % 2 == 1 else args.blur + 1
    if args.threshold is not None:
        config["threshold"] = args.threshold
    if args.input is not None:
        config["input"] = args.input
    if args.output is not None:
        config["output"] = args.output

    # Ensure blur is odd
    blur_strength = config["blur"] if config["blur"] % 2 == 1 else config["blur"] + 1
    threshold = config["threshold"]

    # Get/download model
    print("Loading model...")
    model_path = get_model_path()
    segmentation = SelfieSegmentation(model_path)
    print(f"Model loaded: {model_path}")

    # Open webcam
    print(f"Opening webcam {config['input']}...")
    cap = cv2.VideoCapture(config["input"])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["height"])
    cap.set(cv2.CAP_PROP_FPS, config["fps"])

    if not cap.isOpened():
        print(f"Error: Could not open webcam {config['input']}", file=sys.stderr)
        print("Make sure no other application is using the webcam.", file=sys.stderr)
        return 1

    # Get actual dimensions
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"Webcam opened: {actual_width}x{actual_height} @ {actual_fps}fps")

    # Check virtual camera device
    if not os.path.exists(config["output"]):
        print(f"\nError: Virtual camera {config['output']} not found!", file=sys.stderr)
        print("Run 'blurcam-setup' to configure v4l2loopback.", file=sys.stderr)
        cap.release()
        return 1

    print(f"Opening virtual camera {config['output']}...")

    try:
        with pyvirtualcam.Camera(
            width=actual_width,
            height=actual_height,
            fps=config["fps"],
            device=config["output"],
            fmt=pyvirtualcam.PixelFormat.RGB,
        ) as vcam:
            print(f"Virtual camera started: {vcam.device}")
            print(f"Blur: {blur_strength}")
            print()
            print("Press Ctrl+C to stop")
            print("Adjust blur: blurcam config --blur 45")
            print()

            frame_count = 0
            start_time = time.time()
            last_config_check = time.time()
            config_mtime = get_config_mtime()

            while True:
                ret, frame = cap.read()
                if not ret:
                    print("Error reading frame", file=sys.stderr)
                    break

                # Check for config changes every second
                now = time.time()
                if now - last_config_check >= 1.0:
                    new_mtime = get_config_mtime()
                    if new_mtime > config_mtime:
                        config_mtime = new_mtime
                        new_config = load_config()
                        new_blur = new_config["blur"] if new_config["blur"] % 2 == 1 else new_config["blur"] + 1
                        if new_blur != blur_strength or new_config["threshold"] != threshold:
                            blur_strength = new_blur
                            threshold = new_config["threshold"]
                            print(f"\rSettings updated: blur={blur_strength}  ", flush=True)
                    last_config_check = now

                # Get segmentation mask
                mask = segmentation.get_mask(frame, threshold=threshold)

                # Apply background blur
                result = apply_background_blur(frame, mask, blur_strength)

                # Convert BGR to RGB for virtual camera
                result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)

                # Send to virtual camera
                vcam.send(result_rgb)
                vcam.sleep_until_next_frame()

                # Print FPS every second
                frame_count += 1
                elapsed = time.time() - start_time
                if elapsed >= 1.0:
                    fps = frame_count / elapsed
                    print(f"\rFPS: {fps:.1f}  ", end="", flush=True)
                    frame_count = 0
                    start_time = time.time()

    except KeyboardInterrupt:
        print("\nStopped")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    finally:
        cap.release()

    return 0


def cmd_daemon(args):
    """Run in daemon mode - auto-starts blur when BlurCam is accessed."""
    from .daemon import run_daemon
    from .config import load_config

    config = load_config()
    input_device = args.input if args.input is not None else config["input"]
    output_device = args.output if args.output is not None else config["output"]

    return run_daemon(input_device=input_device, output_device=output_device)


def main():
    parser = argparse.ArgumentParser(
        description="Virtual webcam with AI background blur",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  blurcam                    Run daemon (auto-starts when BlurCam is used)
  blurcam config --blur 45   Adjust blur strength
  blurcam config             Show current settings
  blurcam uninstall          Uninstall completely

The daemon watches BlurCam - blur starts automatically when an app uses it.
        """,
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"blurcam {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Config subcommand
    config_parser = subparsers.add_parser("config", help="View or adjust settings")
    config_parser.add_argument(
        "--blur", "-b",
        type=int,
        help="Blur strength (odd number, default: 35)",
    )
    config_parser.add_argument(
        "--threshold", "-t",
        type=float,
        help="Detection sensitivity 0-1 (advanced, default: 0.5)",
    )

    # Uninstall subcommand
    subparsers.add_parser("uninstall", help="Uninstall blurcam completely")

    # Daemon arguments (on main parser since it's the default)
    parser.add_argument(
        "--input", "-i",
        type=int,
        help="Input webcam device number",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output virtual camera device",
    )
    parser.add_argument(
        "--download-model",
        action="store_true",
        help="Download model and exit",
    )

    args = parser.parse_args()

    # Download model only
    if getattr(args, 'download_model', False):
        from .models import get_model_path
        get_model_path(force_download=True)
        print("Model downloaded successfully!")
        return 0

    # Route to subcommand
    if args.command == "config":
        return cmd_config(args)
    elif args.command == "uninstall":
        return cmd_uninstall(args)
    else:
        return cmd_daemon(args)


if __name__ == "__main__":
    sys.exit(main())
