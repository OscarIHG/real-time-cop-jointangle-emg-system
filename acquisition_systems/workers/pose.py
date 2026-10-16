# -*- coding: utf-8 -*-
"""
PoseWorker: MediaPipe Pose on live camera frames. Publishes PoseSample with
33 landmarks (pixels), their visibility and the pelvic obliquity angle
(landmarks 23 -> 24).

Pipeline (Raspberry Pi oriented):
  camera  -> LatestFrameGrabber thread (keeps only the newest frame + capture time)
  newest  -> inference thread (MediaPipe, model_complexity=0 by default)
  samples -> bounded queue drained by the session coordinator / GUI

The frame is fed to MediaPipe upright. Older releases flipped it vertically,
which showed MediaPipe an upside-down, mirrored person, degraded detection and
inverted the angle sign. A physically rotated camera is handled with
``cam_rotation``, and only the *plot* axis is inverted for display.
"""
import queue
import threading
import time
import warnings
from collections import deque

# Suppress harmless MediaPipe/Protobuf deprecation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf.symbol_database")

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

from acquisition_systems.common.types import PoseSample
from acquisition_systems.common.utils import RateMeter, pelvic_obliquity_deg_from_landmarks, put_counting
from acquisition_systems.common.config import ConfigDict
from acquisition_systems.workers.camera import LatestFrameGrabber, open_frame_source, to_rgb

LM_COUNT = 33


class PoseWorker:
    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480,
                 fps: int = 30, config: ConfigDict = None, queue_size: int = 2000):
        if cv2 is None or mp is None:
            raise ImportError(f"OpenCV and MediaPipe are required: {_pose_import_error}")
        config = config or {}
        self.idx = cam_index
        self.cam_w = int(width)
        self.cam_h = int(height)
        self.fps = max(1, int(fps))
        self.backend = str(config.get("cam_backend", "auto"))
        self.rotation = int(config.get("cam_rotation", 0))
        self.hflip = bool(config.get("cam_hflip", False))
        self.cam_file = str(config.get("cam_file", "") or "")
        self.constant_fps = bool(config.get("cam_constant_fps", False))
        self.min_visibility = float(config.get("pose_min_visibility", 0.5))
        self.model_complexity = int(config.get("mediapipe_model_complexity", 0))  # 0 = fastest
        self.min_detection_confidence = float(config.get("mediapipe_min_detection_confidence", 0.7))
        self.min_tracking_confidence = float(config.get("mediapipe_min_tracking_confidence", 0.5))
        self.smooth_landmarks = bool(config.get("mediapipe_smooth_landmarks", True))
        self.static_image_mode = bool(config.get("mediapipe_static_image_mode", False))

        self.queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self.dropped_samples = 0
        self.capture_rate = RateMeter()
        self.inference_rate = RateMeter()
        self.latency_ms: deque = deque(maxlen=200)   # capture -> landmarks published
        self.detections = 0
        self.processed = 0
        self.error = None
        self.source_name = None

        self._stop = threading.Event()
        self._thread = None
        self._grabber = None
        self._pose_processor = None

    # ---------- setup ----------
    def _init_mediapipe(self):
        self._pose_processor = mp.solutions.pose.Pose(
            static_image_mode=self.static_image_mode,
            model_complexity=self.model_complexity,  # 0 = fastest, 2 = most accurate
            smooth_landmarks=self.smooth_landmarks,
            enable_segmentation=False,
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )

    def _process(self, rgb: np.ndarray, t: float) -> PoseSample:
        results = self._pose_processor.process(rgb)
        h, w = rgb.shape[:2]
        landmarks_px = np.full((LM_COUNT, 2), np.nan, dtype=np.float32)
        visibility = np.zeros(LM_COUNT, dtype=np.float32)
        detected = results.pose_landmarks is not None
        if detected:
            for i, lm in enumerate(results.pose_landmarks.landmark[:LM_COUNT]):
                landmarks_px[i] = (lm.x * w, lm.y * h)  # actual frame size, not the requested one
                visibility[i] = getattr(lm, "visibility", 0.0)
        angle = pelvic_obliquity_deg_from_landmarks(landmarks_px, visibility, self.min_visibility) if detected else float("nan")
        return PoseSample(t=t, landmarks=landmarks_px, angle_deg=angle, detected=detected,
                          visibility=visibility, frame_size=(w, h))

    # ---------- inference loop (single owner of the MediaPipe graph) ----------
    def _loop(self):
        seq = 0
        try:
            while not self._stop.is_set():
                item = self._grabber.wait_newer(seq, timeout=0.5)
                if item is None:
                    if self._grabber.error:
                        self.error = self._grabber.error
                        break
                    continue
                seq, t_capture, payload = item
                self.capture_rate.tick(1, t_capture)
                try:
                    rgb = to_rgb(payload, self._grabber.source.fmt, self.cam_w, self.cam_h, self.rotation, self.hflip)
                    sample = self._process(rgb, t_capture)
                except Exception as e:
                    print(f"[PoseWorker] Error in MediaPipe processing: {e}")
                    time.sleep(0.01)
                    continue
                now = time.perf_counter()
                self.processed += 1
                self.detections += int(sample.detected)
                self.inference_rate.tick(1, now)
                self.latency_ms.append((now - t_capture) * 1000.0)
                if not put_counting(self.queue, sample):
                    self.dropped_samples += 1
        finally:
            processor, self._pose_processor = self._pose_processor, None
            if processor is not None:
                try:
                    processor.close()
                except Exception:
                    pass

    # ---------- Public API ----------
    def start(self):
        """Open the camera, load MediaPipe and start the capture and inference threads."""
        self._stop.clear()
        source = open_frame_source(self.backend, self.idx, self.cam_w, self.cam_h, self.fps, self.cam_file,
                                   self.constant_fps)
        self.source_name = type(source).__name__
        try:
            self._init_mediapipe()
        except Exception:
            source.close()
            raise
        self._grabber = LatestFrameGrabber(source)
        self._grabber.start()
        self._thread = threading.Thread(target=self._loop, name="pose-inference", daemon=True)
        self._thread.start()
        print(f"[PoseWorker] Started - {self.source_name} {self.cam_w}x{self.cam_h} @ {self.fps} fps, "
              f"model_complexity={self.model_complexity}")

    @property
    def frames_dropped(self) -> int:
        return self._grabber.dropped if self._grabber else 0

    def stop(self):
        """Signal both threads; each releases the resource it owns."""
        self._stop.set()
        if self._grabber:
            self._grabber.stop()
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                print("[PoseWorker] WARNING: inference thread still busy; it will release MediaPipe on exit")
            self._thread = None
