# -*- coding: utf-8 -*-
"""
Body-Tracking worker for GUI integration (MediaPipe Pose)
- Captures frames from /dev/video0 with OpenCV
- Extracts 2D landmarks in pixel coordinates
- Computes pelvic obliquity (hip line angle) from keypoints 23 (L hip) and 24 (R hip)
- Pushes landmarks and angle to thread-safe Queues for real-time plots
"""

import cv2
import time
import math
import threading
import queue
import numpy as np
import mediapipe as mp


def pelvic_obliquity_deg(landmarks_px: np.ndarray) -> float:
    """
    Return the angle (deg) of vector 23->24 relative to +x (horizontal).
    Positive when right hip is higher (y up). Image y is down, so invert sign.
    """
    if landmarks_px.shape[0] <= 24:
        return 0.0
    xL, yL = landmarks_px[23, 0], landmarks_px[23, 1]
    xR, yR = landmarks_px[24, 0], landmarks_px[24, 1]
    vx = xR - xL
    vy_img = yR - yL
    vy = -vy_img  # convert to Cartesian (y up)
    ang = math.degrees(math.atan2(vy, vx))  # (-180, 180]
    # Normalize to [-90, 90] for "tilt-like" interpretation
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180
    return ang


class PoseWorker:
    def __init__(self,
                 cam_index: int = 0,
                 width: int = 640,
                 height: int = 480,
                 fps: int = 30):
        """Prepare camera and pose estimator on start()."""
        self.cam_index = cam_index
        self.w = width
        self.h = height
        self.fps = fps

        self.cam = None
        self.pose = None

        self.stop_event = threading.Event()
        self.thread = None

        # Outputs
        # landmarks_q carries an (N,2) float array of [x_px, y_px]
        self.landmarks_q = queue.Queue()
        # angle_q carries a single float (deg)
        self.angle_q = queue.Queue()

    def _open(self):
        self.cam = cv2.VideoCapture(self.cam_index, cv2.CAP_V4L2)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
        self.cam.set(cv2.CAP_PROP_FPS, self.fps)
        self.cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def _reader_loop(self):
        last_t = time.perf_counter()
        try:
            while not self.stop_event.is_set():
                ok, frame = self.cam.read()
                if not ok:
                    continue
                # MediaPipe expects RGB
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = self.pose.process(rgb)

                if res and res.pose_landmarks:
                    lm = res.pose_landmarks.landmark
                    pts = np.array([[int(p.x * self.w), int(p.y * self.h)] for p in lm], dtype=np.float32)
                    # publish landmarks
                    try:
                        self.landmarks_q.put_nowait(pts)
                    except queue.Full:
                        pass
                    # publish angle
                    ang = pelvic_obliquity_deg(pts)
                    try:
                        self.angle_q.put_nowait(float(ang))
                    except queue.Full:
                        pass

                # small pacing to reduce CPU
                now = time.perf_counter()
                if (now - last_t) < 0.005:
                    time.sleep(0.002)
                last_t = now
        finally:
            try:
                self.cam.release()
            except Exception:
                pass

    def start(self):
        self.stop_event.clear()
        self._open()
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.5)
