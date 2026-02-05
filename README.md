# blurcam

**Virtual webcam with AI background blur for Linux**

One command to blur your background on Discord, Zoom, Google Meet, or any video app.

Works on Asahi Linux (Apple Silicon), Raspberry Pi, Ubuntu, Fedora, Arch, and more.

## Install

```bash
curl -sSL https://raw.githubusercontent.com/jolehuit/linux-blurcam/main/scripts/install.sh | bash
```

That's it. The installer:
- Installs [uv](https://docs.astral.sh/uv/) (fast Python manager) if needed
- Installs the v4l2loopback kernel module for your distro
- Creates the virtual camera at `/dev/video10`
- Starts the background daemon that auto-detects when apps use the camera

## Usage

In your video app (Discord, Zoom, Meet...), select **"BlurCam"** as your camera.

That's it. **Blur starts automatically** when an app uses BlurCam, and stops when the app closes.

Your real webcam only turns on when needed - no manual commands required.

### Adjust blur strength

```bash
# See current settings
blurcam config

# Change blur (applies immediately, no restart needed)
blurcam config --blur 45
```

Blur values: `15` = subtle, `35` = default, `55` = strong, `75` = very blurry

### How to test

1. Open your video app (Discord, Zoom, Meet...)
2. Select **"BlurCam"** as your camera
3. You should see yourself with blurred background

## Known Limitations

### Switching cameras in Electron apps (Discord, Vesktop, etc.)

Due to how V4L2 works on Linux (only one process can use the webcam at a time), switching from BlurCam to your real camera may show a black screen.

**Workaround:** Close the camera settings menu, wait 1-2 seconds, then reopen it and select your camera.

This happens because Electron apps don't release the previous camera fast enough when switching. It's a timing issue between the app and the daemon.

## Uninstall

```bash
blurcam uninstall
```

This removes config files, cached model, and systemd service.

## Manual install

If you prefer to install manually:

### 1. Install v4l2loopback

**Fedora / Asahi Linux:**
```bash
sudo dnf install akmod-v4l2loopback
# Asahi only: sudo dnf install kernel-16k-devel && sudo akmods --force
```

**Ubuntu / Debian / Raspberry Pi OS:**
```bash
sudo apt install v4l2loopback-dkms v4l2loopback-utils
```

**Arch Linux:**
```bash
sudo pacman -S v4l2loopback-dkms
```

### 2. Load the kernel module

```bash
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="BlurCam" exclusive_caps=1
```

### 3. Install blurcam

```bash
# With uv (recommended)
uv tool install blurcam

# Or with pipx
pipx install blurcam

# Or with pip
pip install --user blurcam
```

### 4. Run

```bash
blurcam
```

## Auto-start (default)

The installer automatically enables the daemon at boot. The daemon is lightweight - it only watches for app connections and starts the webcam when needed.

### Manual control

```bash
# Check status
systemctl --user status blurcam

# Stop daemon
systemctl --user stop blurcam

# Disable auto-start
systemctl --user disable blurcam
```

### v4l2loopback config (for manual install)

```bash
echo "v4l2loopback" | sudo tee /etc/modules-load.d/v4l2loopback.conf
echo 'options v4l2loopback video_nr=10 card_label="BlurCam" exclusive_caps=1' | \
    sudo tee /etc/modprobe.d/v4l2loopback.conf
```

## Troubleshooting

### "Virtual camera not found"

The kernel module isn't loaded:

```bash
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label="BlurCam" exclusive_caps=1
```

### "Could not open webcam"

Another app is using the camera. Close other video apps first.

### Check system status

```bash
blurcam-setup
```

### Low FPS

On slower devices, reduce blur strength:

```bash
blurcam config --blur 15
```

## Advanced options

```bash
# Detection sensitivity (if edges are cut off or background leaks through)
blurcam config --threshold 0.4   # More inclusive (keeps more of you)
blurcam config --threshold 0.6   # More strict (cleaner edges)

# Use different webcam
blurcam --input 1

# Use different virtual camera
blurcam --output /dev/video20
```

## How it works

1. **Daemon** watches the virtual camera device using inotify
2. When an app opens BlurCam, the daemon starts processing
3. **ONNX Runtime** runs the AI segmentation model on CPU (ARM64 compatible)
4. **OpenCV** captures your webcam and applies background blur
5. **pyvirtualcam** + **v4l2loopback** sends the result to the virtual camera
6. When the app closes, the daemon stops processing (webcam turns off)

The key: using the ONNX model directly instead of MediaPipe Python bindings (which don't support ARM64).

## Compatibility

| Platform | Status |
|----------|--------|
| Asahi Linux (M1/M2/M3) | Tested |
| Raspberry Pi 5 | Not tested yet |
| Raspberry Pi 4 | Not tested yet |
| Ubuntu ARM64 | Not tested yet |
| Fedora ARM64 | Not tested yet |
| Arch ARM | Not tested yet |
| x86_64 Linux | Not tested yet |

## License

MIT License - see [LICENSE](LICENSE)

## Credits

- [ONNX Community](https://huggingface.co/onnx-community) - Exported segmentation model
- [Astral](https://astral.sh/) - uv package manager
- [v4l2loopback](https://github.com/umlaeute/v4l2loopback) - Virtual camera kernel module
- [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) - Python virtual camera library
