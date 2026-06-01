# -*- coding: utf-8 -*-
"""
PoseWorker: captures landmarks using MediaPipe from a camera and publishes:
  - PoseSample: 33 landmarks (33 x 2) in pixel coordinates
  - AngleSample: pelvic obliquity angle (deg) computed from landmarks 23–24

REPLACES the TensorFlow Lite version with superior MediaPipe.
MediaPipe provides 33 landmarks vs 17 from MoveNet, higher precision and temporal tracking.
OPTIMIZED for better performance and FIXED vertical inversion.
"""
import time
import queue
import warnings

# Suppress harmless MediaPipe/Protobuf deprecation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf.symbol_database")

import threading
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
from acquisition_systems.common.utils import put_latest
from acquisition_systems.common.config import ConfigDict


def _calculate_pelvic_obliquity_mediapipe(landmarks: np.ndarray) -> float:
    """
    Calculates pelvic obliquity using MediaPipe landmarks 23 and 24.
    MediaPipe landmarks 23 = left hip, 24 = right hip
    
    Args:
        landmarks: Array (33, 2) with [x, y] coordinates of MediaPipe landmarks
    Returns:
        Angle in degrees (positive = tilt towards right)
    """
    if landmarks.shape[0] < 25:  # Ensure we have at least 25 landmarks
        return 0.0
        
    # Hip landmarks in MediaPipe
    left_hip = landmarks[23]   # Left hip
    right_hip = landmarks[24]  # Right hip
    
    # Check if landmarks are valid (not NaN)
    if np.any(np.isnan([left_hip, right_hip])):
        return 0.0
    
    # Calculate vector from right hip to left hip
    hip_vector = left_hip - right_hip
    
    # Calculate angle with respect to horizontal
    angle_rad = np.arctan2(hip_vector[1], hip_vector[0])
    angle_deg = np.degrees(angle_rad)
    
    # Normalize to range [-90, 90]
    while angle_deg > 90:
        angle_deg -= 180
    while angle_deg < -90:
        angle_deg += 180
    
    return float(angle_deg)


class PoseWorker:
    """
    Pose worker using MediaPipe - Superior to TensorFlow Lite.
    OPTIMIZED for performance and FIXED for correct orientation.
    
    Features:
    - 33 landmarks (vs 17 from MoveNet)
    - Smooth temporal tracking
    - Better precision for joint angles
    - Automatic configuration without external models
    - FIXED: Corrected vertical inversion issue
    - OPTIMIZED: Better performance with reduced resolution and model complexity
    """
    
    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480, 
                 fps: int = 30, config: ConfigDict = None):
        """Initialize PoseWorker with original interface for compatibility."""
        if cv2 is None or mp is None:
            raise ImportError(f"OpenCV and MediaPipe are required: {_pose_import_error}")
        
        self.idx = cam_index
        # OPTIMIZATION: Reduce resolution for better performance
        self.cam_w = int(min(width, 480))   # Max 480 width for performance
        self.cam_h = int(min(height, 360))  # Max 360 height for performance
        self.fps = int(min(fps, 20))        # Max 20 FPS for performance
        
        # MediaPipe configuration - OPTIMIZED for performance
        if config:
            self.model_complexity = int(config.get('mediapipe_model_complexity', 0))  # 0 = fastest
            self.min_detection_confidence = float(config.get('mediapipe_min_detection_confidence', 0.7))
            self.min_tracking_confidence = float(config.get('mediapipe_min_tracking_confidence', 0.5))
            self.smooth_landmarks = bool(config.get('mediapipe_smooth_landmarks', True))
            self.smooth_segmentation = bool(config.get('mediapipe_smooth_segmentation', False))
            self.static_image_mode = bool(config.get('mediapipe_static_image_mode', False))
        else:
            # OPTIMIZED default values for best performance
            self.model_complexity = 0        # Fastest model
            self.min_detection_confidence = 0.7
            self.min_tracking_confidence = 0.5
            self.smooth_landmarks = True
            self.smooth_segmentation = False
            self.static_image_mode = False
        
        self.landmarks_q: queue.Queue = queue.Queue(maxsize=10000)
        self.angle_q: queue.Queue = queue.Queue(maxsize=10000)
        
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cam = None
        self._pose_processor = None
        
        # Performance tracking
        self._frame_count = 0
        self._last_fps_time = time.time()
    
    def _open_camera(self):
        """Open camera with optimized configuration."""
        # Try V4L2 first (better on Linux)
        self._cam = cv2.VideoCapture(self.idx, cv2.CAP_V4L2)
        if not self._cam or not self._cam.isOpened():
            try:
                if self._cam: 
                    self._cam.release()
            except Exception: 
                pass
            # Fallback to default backend
            self._cam = cv2.VideoCapture(self.idx)
        
        if not self._cam or not self._cam.isOpened():
            raise RuntimeError(f"Camera index {self.idx} not available.")
        
        try:
            # OPTIMIZED camera configuration for better performance
            self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_w)
            self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_h)
            self._cam.set(cv2.CAP_PROP_FPS, self.fps)
            self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # CRITICAL: Minimum buffer for real-time
            
            # Additional optimizations
            self._cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
            # Disable auto-exposure and auto-white-balance for consistent performance
            self._cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manual exposure
        except Exception as ex:
            print(f"[PoseWorker] Warning: Could not configure some camera properties: {ex}")
    
    def _init_mediapipe(self):
        """Initialize MediaPipe Pose with optimized configuration."""
        mp_pose = mp.solutions.pose
        
        self._pose_processor = mp_pose.Pose(
            static_image_mode=self.static_image_mode,
            model_complexity=self.model_complexity,  # 0 = fastest, 2 = most accurate
            smooth_landmarks=self.smooth_landmarks,
            smooth_segmentation=self.smooth_segmentation,
            enable_segmentation=False,  # CRITICAL: Disable for much better performance
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence
        )
        
        print(f"[PoseWorker] MediaPipe initialized (OPTIMIZED):")
        print(f"  - Resolution: {self.cam_w}x{self.cam_h} (optimized)")
        print(f"  - Target FPS: {self.fps} (optimized)")
        print(f"  - Model complexity: {self.model_complexity} (0=fastest)")
        print(f"  - Detection confidence: {self.min_detection_confidence}")
        print(f"  - Tracking confidence: {self.min_tracking_confidence}")
        print(f"  - Segmentation: disabled (performance boost)")
    
    def _process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, bool]:
        """
        Processes frame with MediaPipe and converts to pixel coordinates.
        FIXED: Corrects vertical inversion issue.
        
        Returns:
            tuple: (landmarks_array, pose_detected)
            - landmarks_array: (33, 2) array with [x, y] coordinates in pixels
            - pose_detected: bool indicating if pose was detected
        """
        # CRITICAL FIX: Flip frame vertically to correct inversion
        # This fixes the "head at bottom, feet at top" issue
        frame = cv2.flip(frame, 0)  # 0 = flip around x-axis (vertical flip)
        
        # Convert BGR to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Process with MediaPipe
        results = self._pose_processor.process(rgb_frame)
        
        # Initialize landmarks array
        landmarks_px = np.full((33, 2), np.nan, dtype=np.float32)
        pose_detected = False
        
        if results.pose_landmarks:
            pose_detected = True
            
            # Convert normalized landmarks to pixel coordinates
            # Note: After the flip, coordinates are already correctly oriented
            for i, landmark in enumerate(results.pose_landmarks.landmark):
                # MediaPipe returns normalized coordinates [0, 1]
                x_px = landmark.x * self.cam_w
                y_px = landmark.y * self.cam_h
                
                # Check if landmark is visible (confidence > threshold)
                if hasattr(landmark, 'visibility') and landmark.visibility > 0.1:
                    landmarks_px[i, 0] = x_px
                    landmarks_px[i, 1] = y_px
                else:
                    # Include position even with low visibility for continuity
                    landmarks_px[i, 0] = x_px  
                    landmarks_px[i, 1] = y_px
        
        return landmarks_px, pose_detected
    
    def _loop(self):
        """Main acquisition and processing loop - OPTIMIZED for performance."""
        frame_count = 0
        start_time = time.perf_counter()
        skip_counter = 0  # For frame skipping optimization
        
        try:
            while not self._stop.is_set():
                ok, frame = self._cam.read()
                if not ok:
                    time.sleep(0.01)
                    continue
                
                # PERFORMANCE OPTIMIZATION: Skip every other frame if processing is slow
                skip_counter += 1
                if skip_counter % 2 == 0:
                    continue
                
                try:
                    # Process with MediaPipe (includes flip correction)
                    landmarks_px, pose_detected = self._process_frame(frame)
                    t = time.perf_counter()
                    
                    if pose_detected:
                        # Publish pose sample (33 landmarks)
                        try:
                            self.landmarks_q.put_nowait(PoseSample(t=t, landmarks=landmarks_px))
                        except queue.Full:
                            pass
                        
                        # Calculate and publish pelvic obliquity angle
                        angle_deg = _calculate_pelvic_obliquity_mediapipe(landmarks_px)
                        try:
                            self.angle_q.put_nowait(AngleSample(t=t, deg=angle_deg))
                        except queue.Full:
                            pass
                    
                    frame_count += 1
                    
                    # Performance statistics every 100 frames
                    if frame_count % 100 == 0:
                        elapsed = t - start_time
                        fps_actual = frame_count / elapsed if elapsed > 0 else 0
                        print(f"[PoseWorker] Performance: {fps_actual:.1f} FPS, {frame_count} poses detected")
                    
                    # Performance throttling - don't exceed target FPS
                    target_frame_time = 1.0 / self.fps
                    process_time = time.perf_counter() - t
                    sleep_time = target_frame_time - process_time
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                except Exception as e:
                    print(f"[PoseWorker] Error in MediaPipe processing: {e}")
                    time.sleep(0.01)
        
        except Exception as e:
            print(f"[PoseWorker] Error in main loop: {e}")
        
        finally:
            try:
                if self._cam:
                    self._cam.release()
                if self._pose_processor:
                    self._pose_processor.close()
            except Exception:
                pass
    
    # ---------- Public API ----------
    def start(self):
        """Start pose acquisition with MediaPipe."""
        print("[PoseWorker] Starting OPTIMIZED MediaPipe with inversion fix...")
        
        self._stop.clear()
        self._open_camera()
        self._init_mediapipe()
        
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        
        print(f"[PoseWorker] ✅ Started - Camera {self.idx} ({self.cam_w}x{self.cam_h} @ {self.fps}fps)")
    
    def stop(self):
        """Stop acquisition and release resources."""
        print("[PoseWorker] Stopping MediaPipe...")
        
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        print("[PoseWorker] ✅ Stopped correctly")