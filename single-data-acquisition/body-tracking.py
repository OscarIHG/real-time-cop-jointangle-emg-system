# -*- coding: utf-8 -*-
"""
High-FPS Pose with USB Camera (V4L2) and Matplotlib-only UI
- Left subplot: 2D landmarks (points only)
- Right subplot: shoulder tilt angle over time
- Single window (no OpenCV imshow)
- Tuned for max FPS on your camera: 320x180 @ 30fps (16:9), model_complexity=0
- Clean shutdown: Stop button / ESC / 'q' / window close / Ctrl+C (no noisy errors)
- Orientation: 180° rotation enabled by default (toggle with 'r' if needed)
"""

import os
import cv2
import math
import time
import signal
import getpass
import warnings
import numpy as np
import mediapipe as mp
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

# ---------- Quieter desktop / library logs ----------
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")
os.environ.setdefault("QT_ACCESSIBILITY", "0")
os.environ.setdefault("SESSION_MANAGER", "")
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("MPLBACKEND", "TkAgg")
warnings.filterwarnings(
    "ignore",
    message="SymbolDatabase.GetPrototype\\(\\) is deprecated",
    category=UserWarning,
    module="google.protobuf.symbol_database"
)
_username = getpass.getuser()
_xdg = f"/tmp/runtime-{_username}"
os.environ.setdefault("XDG_RUNTIME_DIR", _xdg)
os.makedirs(_xdg, mode=0o700, exist_ok=True)

# ---------- Tunables for speed/FOV ----------
CAPTURE_WIDTH, CAPTURE_HEIGHT = 320, 180   # keep 16:9 and very light CPU
DESIRED_FPS = 30
PIXEL_FORMAT = 'MJPG'          # try 'MJPG' if your backend prefers it
PROCESS_WIDTH, PROCESS_HEIGHT = CAPTURE_WIDTH, CAPTURE_HEIGHT
PRINT_FPS_EVERY = 90           # print loop FPS every N frames
ANGLE_EVERY_N = 2              # update angle plot every N frames (lighter UI)
SMOOTH_ANGLE_ALPHA = 0.25      # EMA smoothing (0=off, 0.2~0.3 recommended)

# Orientation defaults (fix upside-down sensor)
ORIENT_ROT180 = False
ORIENT_HFLIP = False
ORIENT_VFLIP = False

# ---------- Graceful shutdown ----------
running = True
def _shutdown(*_):
    """Signal handler / callbacks set this flag to stop the main loop cleanly."""
    global running
    running = False

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# ---------- Helpers ----------
def apply_orientation(frame, rot180, hflip, vflip):
    """Apply orientation transforms before processing and plotting."""
    if rot180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if hflip:
        frame = cv2.flip(frame, 1)
    if vflip:
        frame = cv2.flip(frame, 0)
    return frame

def shoulder_tilt_deg(lm, idx_left=11, idx_right=12):
    """
    Compute shoulder tilt (deg) with y-axis pointing UP and normalize to [-90, 90].
    0 ≈ level shoulders; positive when right shoulder is higher.
    """
    xL, yL = lm[idx_left, 1], lm[idx_left, 2]
    xR, yR = lm[idx_right, 1], lm[idx_right, 2]
    vx = xR - xL
    vy_img = yR - yL
    vy = -vy_img  # convert to math-style (y up)
    ang = math.degrees(math.atan2(vy, vx))  # (-180, 180]
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180
    return ang

# ---------- Pose detector ----------
class PoseDetector:
    def __init__(self, detection_conf=0.5, track_conf=0.5):
        self.mpPose = mp.solutions.pose
        self.pose = self.mpPose.Pose(
            static_image_mode=False,
            model_complexity=0,       # fastest model
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=detection_conf,
            min_tracking_confidence=track_conf
        )
        self.results = None

    def process(self, bgr_img):
        """Run MediaPipe Pose (no drawing for speed)."""
        img_rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
        self.results = self.pose.process(img_rgb)

    def landmarks_px(self, shape):
        """Return landmarks as (N,3): [id, x_px, y_px]."""
        if not self.results or not self.results.pose_landmarks:
            return np.empty((0, 3), dtype=int)
        h, w = shape[:2]
        pts = []
        for idx, lm in enumerate(self.results.pose_landmarks.landmark):
            cx, cy = int(lm.x * w), int(lm.y * h)
            pts.append([idx, cx, cy])
        return np.array(pts, dtype=int)

# ---------- Main ----------
def main():
    # --- Camera init (V4L2) ---
    cam = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cam.set(cv2.CAP_PROP_FPS, DESIRED_FPS)
    cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # lower latency if supported
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*PIXEL_FORMAT))
    if not cam.isOpened():
        print("[ERROR] Could not open /dev/video0")
        return

    detector = PoseDetector(detection_conf=0.5, track_conf=0.5)

    # --- Matplotlib UI (single window with 2 subplots + Stop button) ---
    plt.ion()
    fig, (ax_pts, ax_ang) = plt.subplots(1, 2, figsize=(12, 6))
    try:
        fig.canvas.manager.set_window_title("Pose (points)  |  Shoulder Tilt")
    except Exception:
        pass
    plt.subplots_adjust(bottom=0.14, right=0.98)  # space for Stop button

    # Left: points only
    ax_pts.set_title("2D landmarks (points only)")
    ax_pts.set_xlim(0, PROCESS_WIDTH)
    ax_pts.set_ylim(0, PROCESS_HEIGHT)
    ax_pts.invert_yaxis()   # image-like coordinates (origin top-left)
    ax_pts.set_aspect('equal')
    ax_pts.grid(True, alpha=0.25)
    scat = ax_pts.scatter([], [], s=12, c='r')

    # Right: shoulder angle
    ax_ang.set_title("Left–Right shoulder tilt (deg)")
    ax_ang.set_xlim(0, 900)
    ax_ang.set_ylim(-90, 90)
    ax_ang.grid(True, alpha=0.3)
    line_angle, = ax_ang.plot([], [], linewidth=2)

    # --- Stop button ---
    btn_ax = fig.add_axes([0.86, 0.02, 0.10, 0.07])  # [left, bottom, width, height]
    stop_btn = Button(btn_ax, "Stop")
    stop_btn.label.set_fontsize(11)
    stop_btn.color = "#e74c3c"
    stop_btn.hovercolor = "#c0392b"
    def on_stop(_event):
        _shutdown()
    stop_btn.on_clicked(on_stop)

    # Keyboard: ESC/q to exit, 'r' toggles 180° rotation
    def on_key(event):
        k = (event.key or "").lower()
        if k in ("escape", "q"):
            _shutdown()
        elif k == "r":
            # toggle 180° rotation at runtime
            global ORIENT_ROT180
            ORIENT_ROT180 = not ORIENT_ROT180
            print(f"[INFO] Rotate 180° = {ORIENT_ROT180}")

    def on_close(_event):
        _shutdown()

    fig.canvas.mpl_connect('key_press_event', on_key)
    fig.canvas.mpl_connect('close_event', on_close)

    # Loop state
    L_SHO, R_SHO = 11, 12
    xs, ys = [], []
    angle_smooth = None
    t = 0
    last_fps_t = time.perf_counter()

    try:
        while running:
            try:
                ok, frame = cam.read()
            except KeyboardInterrupt:
                _shutdown()
                break
            if not ok:
                if running:
                    print("[ERROR] Failed to capture frame.")
                break

            # Ensure processing size and orientation
            if (frame.shape[1], frame.shape[0]) != (PROCESS_WIDTH, PROCESS_HEIGHT):
                frame = cv2.resize(frame, (PROCESS_WIDTH, PROCESS_HEIGHT), interpolation=cv2.INTER_LINEAR)
            frame = apply_orientation(frame, ORIENT_ROT180, ORIENT_HFLIP, ORIENT_VFLIP)

            # MediaPipe (no drawing)
            detector.process(frame)
            lm = detector.landmarks_px(frame.shape)

            # Update points
            if lm.shape[0] > 0:
                scat.set_offsets(lm[:, 1:3])
            else:
                scat.set_offsets(np.empty((0, 2)))

            # Update angle plot every N frames
            if lm.shape[0] > R_SHO and (t % ANGLE_EVERY_N == 0):
                ang = shoulder_tilt_deg(lm, L_SHO, R_SHO)
                if 0.0 < SMOOTH_ANGLE_ALPHA < 1.0:
                    angle_smooth = ang if angle_smooth is None else \
                        (1 - SMOOTH_ANGLE_ALPHA) * angle_smooth + SMOOTH_ANGLE_ALPHA * ang
                    ang_plot = angle_smooth
                else:
                    ang_plot = ang
                xs.append(t); ys.append(ang_plot)
                if len(xs) > 900:
                    xs = xs[-900:]; ys = ys[-900:]
                line_angle.set_data(xs, ys)
                ax_ang.relim(); ax_ang.autoscale_view(scalex=True, scaley=False)

            # FPS print (amortized)
            if t and (t % PRINT_FPS_EVERY == 0):
                now = time.perf_counter()
                fps = PRINT_FPS_EVERY / max(1e-6, (now - last_fps_t))
                print(f"FPS (loop): {fps:.2f} | fmt={PIXEL_FORMAT} {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} | rot180={ORIENT_ROT180}")
                last_fps_t = now

            t += 1
            plt.pause(0.001)  # process GUI events and refresh artists

    finally:
        cam.release()
        plt.ioff()
        try:
            plt.close(fig)
        except Exception:
            pass
        print("[INFO] Camera closed, resources released.")

if __name__ == "__main__":
    main()
