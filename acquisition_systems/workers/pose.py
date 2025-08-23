# PoseWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
PoseWorker: captures MediaPipe Pose landmarks from a camera and publishes:
  - PoseSample: 2D landmarks (33 x 2) in pixel coordinates
  - AngleSample: pelvic obliquity angle (deg) computed from landmarks 23–24

Queues are single-item (latest-only) to avoid backpressure in the GUI/recorder.

Lifecycle:
    w = PoseWorker(cam_index=0, width=640, height=480, fps=30)
    w.start()
    # read from w.landmarks_q and w.angle_q
    w.stop()
"""
import time
import threading
import queue
import numpy as np

try:
    import cv2
    import mediapipe_rpi4 as mp
except Exception as e:
    cv2 = None
    mp = None
    _pose_import_error = e
else:
    _pose_import_error = None

from acquisition_systems.common.types import PoseSample, AngleSample
from acquisition_systems.common.utils import put_latest, pelvic_obliquity_deg_from_landmarks


class PoseWorker:
    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480, fps: int = 30):
        """
        :param cam_index: OpenCV camera index (0,1,...)
        :param width: desired capture width in pixels
        :param height: desired capture height in pixels
        :param fps: desired capture FPS
        """
        if cv2 is None or mp is None:
            raise ImportError(f"OpenCV and MediaPipe are required for PoseWorker: {_pose_import_error}")

        self.idx = cam_index
        self.w = int(width)
        self.h = int(height)
        self.fps = int(fps)

        # Latest-only queues
        self.landmarks_q: queue.Queue = queue.Queue(maxsize=1)
        self.angle_q: queue.Queue = queue.Queue(maxsize=1)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cam = None
        self._pose = None

    # ---------- camera / pose setup ----------
    def _open(self):
        """
        Open camera and instantiate MediaPipe Pose. If the camera cannot be opened,
        raise RuntimeError so the forgiving launcher marks this device OFFLINE.
        """
        # Try V4L2 first (often best on Linux)
        self._cam = cv2.VideoCapture(self.idx, cv2.CAP_V4L2)
        if not self._cam or not self._cam.isOpened():
            # Fallback: default backend
            try:
                if self._cam:
                    self._cam.release()
            except Exception:
                pass
            self._cam = cv2.VideoCapture(self.idx)

        # Final check
        if not self._cam or not self._cam.isOpened():
            raise RuntimeError(f"Camera index {self.idx} not available or cannot be opened")

        # Set desired properties (best-effort)
        try:
            self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
            self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
            self._cam.set(cv2.CAP_PROP_FPS, self.fps)
            # Reduce latency (not all backends support this)
            self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # MediaPipe Pose
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,           # fast model
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    # ---------- acquisition loop ----------
    def _loop(self):
        try:
            while not self._stop.is_set():
                ok, frame = self._cam.read()
                if not ok:
                    # brief pause to avoid busy spin if camera stalls
                    time.sleep(0.01)
                    continue

                # Convert and process
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = self._pose.process(rgb)

                if res is not None and getattr(res, "pose_landmarks", None):
                    lm = res.pose_landmarks.landmark
                    # px coords in current configured width/height
                    pts = np.array([[float(p.x * self.w), float(p.y * self.h)] for p in lm], dtype=np.float32)
                    t = time.perf_counter()

                    # Publish latest pose sample
                    put_latest(self.landmarks_q, PoseSample(t=t, landmarks=pts))

                    # Compute and publish joint angle (pelvic obliquity 23–24)
                    ang = float(pelvic_obliquity_deg_from_landmarks(pts))
                    put_latest(self.angle_q, AngleSample(t=t, deg=ang))
                else:
                    # No detection in this frame; keep loop responsive
                    time.sleep(0.002)
        finally:
            try:
                if self._cam:
                    self._cam.release()
            except Exception:
                pass
            try:
                if self._pose:
                    self._pose.close()  # newer mediapipe has close(); ignore if missing
            except Exception:
                pass

    # ---------- public API ----------
    def start(self):
        """Open camera, init MediaPipe, and start capture thread."""
        self._stop.clear()
        self._open()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Request stop and join the thread; releases resources."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
