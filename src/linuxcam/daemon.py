"""
Daemon mode for blurcam - always produces frames, blur activates when consumers connect.
Uses inotify for instant detection of consumer connect/disconnect.
"""

import os
import signal
import sys
import threading
import time

import numpy as np
from inotify_simple import INotify, flags


class BlurDaemon:
    """Always writes to virtual cam. Blur activates when consumers connect."""

    def __init__(self, device="/dev/video10", input_device=0):
        self.device = device
        self.input_device = input_device
        self.blur_active = False
        self.stop_event = threading.Event()
        self.consumer_event = threading.Event()  # Set when consumer state changes
        self.has_consumers = False

        # Load config
        from .config import load_config
        self.config = load_config()

        self.width = self.config["width"]
        self.height = self.config["height"]
        self.fps = self.config["fps"]

    def _get_consumer_count(self):
        """Count processes that have the device open (excluding ourselves)."""
        my_pid = os.getpid()
        count = 0

        try:
            for pid_dir in os.listdir('/proc'):
                if not pid_dir.isdigit():
                    continue
                pid = int(pid_dir)
                if pid == my_pid:
                    continue
                try:
                    fd_dir = f'/proc/{pid}/fd'
                    for fd in os.listdir(fd_dir):
                        try:
                            target = os.readlink(f'{fd_dir}/{fd}')
                            if target == self.device:
                                count += 1
                                break
                        except (OSError, PermissionError):
                            pass
                except (OSError, PermissionError):
                    pass
        except Exception:
            pass

        return count

    def _inotify_watcher(self):
        """Watch for open/close events on the virtual camera device."""
        inotify = INotify()
        watch_flags = flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE

        try:
            wd = inotify.add_watch(self.device, watch_flags)
        except Exception as e:
            print(f"Warning: Could not watch {self.device}: {e}", file=sys.stderr, flush=True)
            return

        while not self.stop_event.is_set():
            # Read with timeout so we can check stop_event
            events = inotify.read(timeout=500)

            for event in events:
                if event.mask & flags.OPEN:
                    # Someone opened the device - check if it's a real consumer
                    time.sleep(0.05)  # Brief delay for fd to be registered
                    consumers = self._get_consumer_count()
                    if consumers > 0:
                        self.has_consumers = True
                        self.consumer_event.set()

                elif event.mask & (flags.CLOSE_NOWRITE | flags.CLOSE_WRITE):
                    # Someone closed the device - check if consumers remain
                    time.sleep(0.05)  # Brief delay for fd to be unregistered
                    consumers = self._get_consumer_count()
                    if consumers == 0:
                        self.has_consumers = False
                        self.consumer_event.set()

        inotify.close()

    def run(self):
        """Main daemon loop - always writes frames."""
        import cv2
        import pyvirtualcam
        from .models import get_model_path
        from .segmentation import SelfieSegmentation, apply_background_blur
        from .config import load_config, get_config_mtime

        print(f"blurcam daemon started", flush=True)
        print(f"Virtual camera: {self.device}", flush=True)
        print(f"Press Ctrl+C to stop", flush=True)
        print(flush=True)

        # Check if device exists
        if not os.path.exists(self.device):
            print(f"Error: {self.device} not found", file=sys.stderr, flush=True)
            print("Run 'blurcam-setup' to configure v4l2loopback.", file=sys.stderr, flush=True)
            return 1

        # Handle signals
        def signal_handler(sig, frame):
            print("\nShutting down...", flush=True)
            self.stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start inotify watcher thread
        watcher_thread = threading.Thread(target=self._inotify_watcher, daemon=True)
        watcher_thread.start()

        # Lazy-load model and webcam (only when needed)
        segmentation = None
        cap = None
        model_path = None

        # Create black frame for idle mode
        black_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        config_mtime = get_config_mtime()
        blur_strength = self.config["blur"]
        if blur_strength % 2 == 0:
            blur_strength += 1
        threshold = self.config["threshold"]

        try:
            with pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                device=self.device,
                fmt=pyvirtualcam.PixelFormat.RGB,
            ) as vcam:
                print(f"Virtual camera ready: {vcam.device}", flush=True)
                print(f"Select 'BlurCam' in your video app", flush=True)
                print(flush=True)

                while not self.stop_event.is_set():
                    # Check for consumer state changes (non-blocking)
                    if self.consumer_event.is_set():
                        self.consumer_event.clear()

                        if self.has_consumers and not self.blur_active:
                            # Consumer connected - start blur
                            print(f"Consumer connected - starting blur", flush=True)
                            self.blur_active = True

                            # Load model if needed
                            if segmentation is None:
                                model_path = get_model_path()
                                segmentation = SelfieSegmentation(model_path)

                            # Open webcam
                            if cap is None or not cap.isOpened():
                                cap = cv2.VideoCapture(self.input_device)
                                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                                cap.set(cv2.CAP_PROP_FPS, self.fps)

                                if not cap.isOpened():
                                    print(f"Error: Could not open webcam", file=sys.stderr, flush=True)
                                    self.blur_active = False

                        elif not self.has_consumers and self.blur_active:
                            # No consumers - stop blur IMMEDIATELY
                            print(f"No consumers - releasing webcam", flush=True)
                            self.blur_active = False

                            # Release webcam immediately
                            if cap is not None:
                                cap.release()
                                cap = None

                    # Check for config changes
                    new_mtime = get_config_mtime()
                    if new_mtime > config_mtime:
                        config_mtime = new_mtime
                        self.config = load_config()
                        blur_strength = self.config["blur"]
                        if blur_strength % 2 == 0:
                            blur_strength += 1
                        threshold = self.config["threshold"]

                    # Generate frame
                    if self.blur_active and cap is not None and cap.isOpened():
                        ret, frame = cap.read()
                        if ret:
                            # Apply blur
                            mask = segmentation.get_mask(frame, threshold=threshold)
                            result = apply_background_blur(frame, mask, blur_strength)
                            result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
                            vcam.send(result_rgb)
                        else:
                            vcam.send(black_frame)
                    else:
                        # Send black frame when idle
                        vcam.send(black_frame)

                    vcam.sleep_until_next_frame()

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr, flush=True)
            return 1
        finally:
            if cap is not None:
                cap.release()

        return 0


def run_daemon(input_device=0, output_device="/dev/video10"):
    """Entry point for daemon mode."""
    daemon = BlurDaemon(device=output_device, input_device=input_device)
    return daemon.run()
