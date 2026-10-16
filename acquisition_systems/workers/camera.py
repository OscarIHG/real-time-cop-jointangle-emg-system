# -*- coding: utf-8 -*-
"""
Camera frame sources and a latest-frame grabber.

Sources:
  * OpenCVSource  USB/UVC webcams through V4L2 (Linux) or the default backend (Windows)
  * RpicamSource  Raspberry Pi CSI cameras (e.g. the Rpi P5V04A V1.3 / OV5647) via
                  `rpicam-vid` (or `libcamera-vid`) streaming raw YUV420 to stdout.
                  On Raspberry Pi OS Bookworm/Trixie CSI cameras are only exposed
                  through libcamera, so cv2.VideoCapture cannot open them.
  * FileSource    replays an image or video at a fixed rate (benchmarks over SSH)

``LatestFrameGrabber`` reads continuously in its own thread and keeps only the
newest frame with its capture timestamp, so inference never works on stale
buffered frames and capture is decoupled from inference and from the GUI.
"""

import os
import shutil
import subprocess
import threading
import time
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - handled by callers
    cv2 = None


class OpenCVSource:
    fmt = "bgr"

    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 30,
                 constant_fps: bool = False):
        self.index, self.width, self.height, self.fps = index, width, height, fps
        self.constant_fps = constant_fps
        self.cap = None

    def open(self) -> None:
        backend = cv2.CAP_V4L2 if os.name == "posix" and os.path.exists("/dev/video0") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            raise RuntimeError(f"Camera index {self.index} not available.")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        if self.constant_fps and shutil.which("v4l2-ctl"):
            # Many UVC cameras halve their frame rate in dim light when this
            # control is on (7.6 instead of ~19 fps measured on the Pi 4).
            subprocess.run(["v4l2-ctl", "-d", f"/dev/video{self.index}", "-c", "exposure_dynamic_framerate=0"],
                           capture_output=True, timeout=5)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None:
            return False, None
        return self.cap.read()

    def close(self) -> None:
        cap, self.cap = self.cap, None
        if cap is not None:
            cap.release()


def rpicam_binary() -> Optional[str]:
    return shutil.which("rpicam-vid") or shutil.which("libcamera-vid")


def rpicam_has_camera() -> bool:
    hello = shutil.which("rpicam-hello") or shutil.which("libcamera-hello")
    if not hello:
        return False
    try:
        out = subprocess.run([hello, "--list-cameras"], capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    text = (out.stdout or "") + (out.stderr or "")
    return "Available cameras" in text and "No cameras" not in text


class RpicamSource:
    """Raw I420 frames from rpicam-vid; each frame is exactly W*H*3/2 bytes."""

    fmt = "i420"

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width, self.height, self.fps = width, height, fps
        self.frame_bytes = width * height * 3 // 2
        self.proc: Optional[subprocess.Popen] = None

    def open(self) -> None:
        binary = rpicam_binary()
        if not binary:
            raise RuntimeError("rpicam-vid/libcamera-vid not found")
        cmd = [binary, "-t", "0", "-n", "--codec", "yuv420", "--width", str(self.width),
               "--height", str(self.height), "--framerate", str(self.fps), "--flush", "-o", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     bufsize=self.frame_bytes)
        ok, _ = self.read()
        if not ok:
            self.close()
            raise RuntimeError("rpicam-vid produced no frames (is a CSI camera connected?)")

    def read(self) -> Tuple[bool, Optional[bytes]]:
        if self.proc is None or self.proc.stdout is None:
            return False, None
        buf = bytearray(self.frame_bytes)
        view = memoryview(buf)
        got = 0
        while got < self.frame_bytes:
            n = self.proc.stdout.readinto(view[got:])
            if not n:
                return False, None
            got += n
        return True, bytes(buf)

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()


class FileSource:
    """Replays an image (repeated) or a video (looped) at ``fps``."""

    fmt = "bgr"

    def __init__(self, path: str, fps: int = 30, width: int = 640, height: int = 480):
        self.path, self.fps, self.width, self.height = path, max(1, fps), width, height
        self._image = None
        self._cap = None
        self._next = 0.0

    def open(self) -> None:
        if not os.path.exists(self.path):
            raise RuntimeError(f"cam_file not found: {self.path}")
        image = cv2.imread(self.path)
        if image is not None:
            self._image = cv2.resize(image, (self.width, self.height))
        else:
            self._cap = cv2.VideoCapture(self.path)
            if not self._cap.isOpened():
                raise RuntimeError(f"cannot open {self.path}")
        self._next = time.perf_counter()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        delay = self._next - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        self._next = max(self._next + 1.0 / self.fps, time.perf_counter() - 1.0)
        if self._image is not None:
            return True, self._image.copy()
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if ok:
            frame = cv2.resize(frame, (self.width, self.height))
        return ok, frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._image = None


def open_frame_source(backend: str, index: int, width: int, height: int, fps: int, path: str = "",
                      constant_fps: bool = False):
    """Create and open a source. ``auto`` prefers a detected CSI camera, else OpenCV."""
    if cv2 is None:
        raise ImportError("OpenCV is required for camera capture")
    if backend == "file":
        source = FileSource(path, fps, width, height)
    elif backend == "rpicam" or (backend == "auto" and rpicam_binary() and rpicam_has_camera()):
        source = RpicamSource(width, height, fps)
    else:
        source = OpenCVSource(index, width, height, fps, constant_fps)
    source.open()
    return source


def to_rgb(payload, fmt: str, width: int, height: int, rotation: int = 0, hflip: bool = False) -> np.ndarray:
    """Convert a captured payload to an upright RGB image for MediaPipe."""
    if fmt == "i420":
        yuv = np.frombuffer(payload, dtype=np.uint8).reshape(height * 3 // 2, width)
        rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
    else:
        rgb = cv2.cvtColor(payload, cv2.COLOR_BGR2RGB)
    if rotation == 90:
        rgb = cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        rgb = cv2.rotate(rgb, cv2.ROTATE_180)
    elif rotation == 270:
        rgb = cv2.rotate(rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if hflip:
        rgb = cv2.flip(rgb, 1)
    return rgb


class LatestFrameGrabber:
    """Background reader that keeps only the newest frame (older ones are dropped)."""

    def __init__(self, source):
        self.source = source
        self.captured = 0
        self.consumed = 0
        self.error: Optional[str] = None
        self._cond = threading.Condition()
        self._latest = None  # (seq, t_capture, payload)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera-grabber", daemon=True)

    @property
    def dropped(self) -> int:
        return max(0, self.captured - self.consumed)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        failures = 0
        try:
            while not self._stop.is_set():
                ok, payload = self.source.read()
                t = time.perf_counter()
                if not ok:
                    failures += 1
                    if failures > 100:
                        self.error = "camera stopped delivering frames"
                        break
                    time.sleep(0.01)
                    continue
                failures = 0
                with self._cond:
                    self.captured += 1
                    self._latest = (self.captured, t, payload)
                    self._cond.notify_all()
        finally:
            # The grabber thread is the only owner of the device.
            try:
                self.source.close()
            except Exception:
                pass
            with self._cond:
                self._cond.notify_all()

    def wait_newer(self, seq: int, timeout: float = 0.5):
        """Return (seq, t_capture, payload) newer than ``seq`` or None on timeout/stop."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._latest is None or self._latest[0] <= seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set() or not self._thread.is_alive():
                    return None
                self._cond.wait(remaining)
            self.consumed += 1
            return self._latest

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout)
