# PoseWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
PoseWorker: MediaPipe Pose landmarks from a USB camera.
Publishes PoseSample (landmarks) and AngleSample (hip 23–24 obliquity) to
single-item queues (latest only).
"""
import time
import threading
import queue
import numpy as np

try:
    import cv2
    import mediapipe as mp
except Exception as e:
    cv2 = None
    mp = None
    _pose_import_error = e
else:
    _pose_import_error = None

from acquisition_systems.common.types import PoseSample, AngleSample
from acquisition_systems.common.utils import put_latest, pelvic_obliquity_deg_from_landmarks


class PoseWorker:
    """
    Start/stop lifecycle:
      w = PoseWorker(cam_index=0, width=640, height=480, fps=30)
      w.start(); ... read w.landmarks_q / w.angle_q ... ; w.stop()
    """
    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480, fps: int = 30):
        if cv2 is None or mp is None:
            raise ImportError(f"OpenCV and MediaPipe are required for PoseWorker: {_pose_import_error}")

        self.idx = cam_index
        self.w = width
        self.h = height
        self.fps = fps

        self.landmarks_q: queue.Queue = queue.Queue(maxsize=1)
        self.angle_q: queue.Queue = queue.Queue(maxsize=1)

        self._stop = threading.Event()
        self._thread = None
        self._cam = None
        self._pose = None

    def _open(self):
        self._cam = cv2.VideoCapture(self.idx, cv2.CAP_V4L2)
        self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
        self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
        self._cam.set(cv2.CAP_PROP_FPS, self.fps)
        self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def _loop(self):
        try:
            while not self._stop.is_set():
                ok, frame = self._cam.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = self._pose.process(rgb)

                if res and res.pose_landmarks:
                    lm = res.pose_landmarks.landmark
                    pts = np.array([[float(p.x * self.w), float(p.y * self.h)] for p in lm], dtype=np.float32)
                    t = time.perf_counter()
                    put_latest(self.landmarks_q, PoseSample(t=t, landmarks=pts))
                    ang = pelvic_obliquity_deg_from_landmarks(pts)
                    put_latest(self.angle_q, AngleSample(t=t, deg=float(ang)))
                else:
                    time.sleep(0.002)
        finally:
            try:
                self._cam.release()
            except Exception:
                pass

    # ------------ public API ------------
    def start(self):
        self._stop.clear()
        self._open()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
