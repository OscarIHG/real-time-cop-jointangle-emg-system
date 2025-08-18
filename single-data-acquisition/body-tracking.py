# -*- coding: utf-8 -*-
"""
Pose + USB Camera (V4L2/MJPG) + Matplotlib live plots
- Uses MediaPipe Pose to get landmarks
- Plots skeleton (matplotlib) and live shoulder tilt angle over time
- Opens a small OpenCV preview window (you can hit ESC there)
- Clean shutdown on ESC / window close / Ctrl+C

Notes:
- All code comments and printed strings are in English (as requested).
"""

import os
import cv2
import math
import time
import signal
import getpass
import numpy as np
import mediapipe as mp
import matplotlib.pyplot as plt

# ---------- Quiet down common desktop warnings (harmless but noisy) ----------
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")
os.environ.setdefault("QT_ACCESSIBILITY", "0")
os.environ.setdefault("SESSION_MANAGER", "")
_username = getpass.getuser()
_xdg = f"/tmp/runtime-{_username}"
os.environ.setdefault("XDG_RUNTIME_DIR", _xdg)
os.makedirs(_xdg, mode=0o700, exist_ok=True)

# ---------- Graceful shutdown flag ----------
running = True
def _shutdown(*_):
    """Set the running flag to False on SIGINT/SIGTERM."""
    global running
    running = False

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# ---------- Pose detector wrapper ----------
class PoseDetector:
    def __init__(self, static_mode=False, smooth=True, detection_conf=0.5, track_conf=0.5):
        self.pTime = 0.0
        self.mpDraw = mp.solutions.drawing_utils
        self.mpPose = mp.solutions.pose
        self.pose = self.mpPose.Pose(
            static_image_mode=static_mode,
            smooth_landmarks=smooth,
            min_detection_confidence=detection_conf,
            min_tracking_confidence=track_conf
        )
        self.results = None
        self.lmList = []

    def findPose(self, bgr_img, draw=True, draw_on="zeros"):
        """
        Process image with MediaPipe Pose.
        draw_on: "zeros" -> draw landmarks on a black canvas of same size,
                 "image" -> draw on the original image,
                 None     -> no drawing.
        Returns the canvas used for drawing (or a copy of the original).
        """
        img_rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
        self.results = self.pose.process(img_rgb)

        if draw_on == "zeros":
            canvas = np.zeros_like(bgr_img)
            target = canvas
        elif draw_on == "image":
            canvas = bgr_img.copy()
            target = canvas
        else:
            # no drawing
            return bgr_img.copy()

        if self.results.pose_landmarks and draw:
            self.mpDraw.draw_landmarks(
                target,
                self.results.pose_landmarks,
                self.mpPose.POSE_CONNECTIONS
            )
        return canvas

    def getPosition(self, reference_img_shape):
        """
        Build a landmark list (id, x_px, y_px) for current results.
        reference_img_shape: tuple (H, W, C) to convert normalized coords to pixels.
        """
        self.lmList = []
        if not self.results or not self.results.pose_landmarks:
            return np.empty((0, 3), dtype=int)

        h, w = reference_img_shape[:2]
        for idx, lm in enumerate(self.results.pose_landmarks.landmark):
            cx, cy = int(lm.x * w), int(lm.y * h)
            self.lmList.append([idx, cx, cy])
        return np.array(self.lmList, dtype=int)

    def showFps(self, img_to_draw_on):
        """Compute and print FPS, also overlay text on provided image (numpy array)."""
        cTime = time.time()
        fps = 1.0 / max(1e-6, (cTime - self.pTime))
        self.pTime = cTime
        print(f"FPS: {fps:.2f}")
        cv2.putText(img_to_draw_on, str(int(fps)), (70, 80),
                    cv2.FONT_HERSHEY_PLAIN, 3, (255, 0, 0), 3)

# ---------- Main ----------
def main():
    # --- Camera init (V4L2 + MJPG to reduce CPU on RPi) ---
    cam = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cam.set(cv2.CAP_PROP_FPS, 30)
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    if not cam.isOpened():
        print("[ERROR] Could not open /dev/video0")
        return

    cv2.namedWindow("USB Camera (press ESC to exit)", cv2.WINDOW_AUTOSIZE)
    print("[INFO] Press ESC, close the window, or Ctrl+C to exit.")

    # --- Pose detector ---
    detector = PoseDetector(static_mode=False, smooth=True, detection_conf=0.5, track_conf=0.5)

    # --- Matplotlib setup (skeleton + shoulder tilt angle) ---
    plt.ion()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
    ax1.set_title("Skeleton (2D)")
    ax2.set_title("Left–Right shoulder tilt (deg)")
    xs, ys = [], []
    t = 0

    # We will adjust axis limits dynamically after first frame to match processed size.
    skel_initialized = False
    line_angle, = ax2.plot([], [], 'b', linewidth=2)

    # Mediapipe landmark indices:
    # 11 = left shoulder, 12 = right shoulder
    L_SHO = 11
    R_SHO = 12

    try:
        while running:
            ok, frame = cam.read()
            if not ok:
                print("[ERROR] Failed to capture frame.")
                break

            # Optional: downscale to 640x480 for faster CPU on RPi and consistent plotting
            proc = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)

            # Run pose and draw landmarks on a black canvas for matplotlib,
            # and also overlay on the OpenCV preview for convenience.
            canvas = detector.findPose(proc, draw=True, draw_on="zeros")
            preview = detector.findPose(proc, draw=True, draw_on="image")  # for cv2.imshow

            # Build landmark pixel array (id, x, y) based on processed image shape
            lm = detector.getPosition(proc.shape)

            # Show FPS on the OpenCV preview
            detector.showFps(preview)
            cv2.imshow("USB Camera (press ESC to exit)", preview)

            # Exit conditions from OpenCV side
            key = cv2.waitKey(1) & 0xFF
            if key == 27 or cv2.getWindowProperty("USB Camera (press ESC to exit)", cv2.WND_PROP_VISIBLE) < 1:
                break

            # Plot skeleton and angle only if we have enough landmarks
            if lm.shape[0] >= 13:  # shoulders exist
                # Prepare matplotlib axes once (match the processed frame size)
                if not skel_initialized:
                    h, w = proc.shape[:2]
                    ax1.set_xlim(0, w)
                    ax1.set_ylim(0, h)
                    ax1.invert_yaxis()  # so origin (0,0) is top-left like image coordinates
                    ax1.set_aspect('equal')
                    ax2.set_xlim(0, 1000)  # will autoscale later; start with a window
                    ax2.set_ylim(-90, 90)
                    skel_initialized = True

                # Scatter the keypoints
                ax1.clear()
                ax1.set_title("Skeleton (2D)")
                ax1.set_xlim(0, w); ax1.set_ylim(0, h); ax1.invert_yaxis(); ax1.set_aspect('equal')
                ax1.grid(True, alpha=0.3)

                X = lm[:, 1]
                Y = lm[:, 2]
                ax1.plot(X, Y, 'ro', markersize=4)

                # Simple connections similar to POSE_CONNECTIONS (subset)
                # You can expand these as needed.
                def _pl(idx_list):
                    ax1.plot(X[idx_list], Y[idx_list], 'b')

                # Torso & arms & legs (roughly following your original choices)
                if lm.shape[0] > 32:  # ensure all indices exist before plotting segments
                    _pl([11, 12, 24, 23, 11])                           # shoulders-hips box
                    _pl([11, 13, 15, 17, 15, 13, 11])                    # left arm + hand loop
                    _pl([12, 14, 16, 18, 16, 14, 12])                    # right arm + hand loop
                    _pl([23, 25, 27, 29, 31, 27])                        # left leg
                    _pl([24, 26, 28, 30, 32, 28])                        # right leg
                    _pl([11, 12])                                        # shoulders
                    _pl([23, 24])                                        # hips

                # Shoulder tilt angle (deg): atan2(yL - yR, xL - xR)
                xL, yL = lm[L_SHO, 1], lm[L_SHO, 2]
                xR, yR = lm[R_SHO, 1], lm[R_SHO, 2]
                angle_deg = math.degrees(math.atan2((yL - yR), (xL - xR)))

                t += 1
                xs.append(t)
                ys.append(angle_deg)
                line_angle.set_data(xs, ys)

                # Keep last ~1000 samples visible
                if len(xs) > 1000:
                    xs = xs[-1000:]
                    ys = ys[-1000:]
                    line_angle.set_data(xs, ys)

                ax2.relim()
                ax2.autoscale_view()

                # Refresh figure
                plt.pause(0.001)

    finally:
        # Always release resources (even on Ctrl+C/SIGTERM)
        cam.release()
        cv2.destroyAllWindows()
        plt.ioff()
        try:
            plt.close(fig)
        except Exception:
            pass
        print("[INFO] Camera closed, resources released.")

if __name__ == "__main__":
    main()
