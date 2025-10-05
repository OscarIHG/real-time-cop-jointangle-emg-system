# acquisition_systems/workers/pose.py

"""
Pose tracking worker using MediaPipe.
Handles pose detection, landmark processing, and angle calculations.
"""

from __future__ import annotations
import time
from threading import Thread, Event
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

import cv2
import mediapipe as mp
import numpy as np

from acquisition_systems.common.config import ConfigDict


@dataclass
class PoseData:
    """Container for pose detection results."""
    timestamp: float
    landmarks: Optional[List[Tuple[float, float, float]]] = None  # (x, y, z) normalized
    angles: Optional[Dict[str, float]] = None
    frame_available: bool = False
    fps: float = 0.0


class PoseWorker:
    """
    Optimized MediaPipe pose tracking worker.
    Handles camera capture, pose detection, and angle calculations.
    """
    
    def __init__(self, config: ConfigDict):
        self.config = config
        self.running = Event()
        self.thread: Optional[Thread] = None
        self.latest_data = PoseData(timestamp=time.time())
        
        # Camera settings - OPTIMIZED for better performance
        self.cam_index = config.get('cam_index', 0)
        self.cam_width = config.get('cam_width', 480)   # Reduced from 640
        self.cam_height = config.get('cam_height', 360) # Reduced from 480
        self.target_fps = config.get('cam_fps', 20)     # Reduced from 30
        
        # MediaPipe configuration - OPTIMIZED
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            model_complexity=0,  # REDUCED: 0 is fastest, 2 is most accurate
            min_detection_confidence=0.7,   # INCREASED for better reliability
            min_tracking_confidence=0.5,    # Standard value
            smooth_landmarks=True,
            enable_segmentation=False,      # DISABLED for better performance
            smooth_segmentation=False
        )
        
        self.mp_drawing = mp.solutions.drawing_utils
        self.cap: Optional[cv2.VideoCapture] = None
        
        # Performance tracking
        self._frame_times = []
        self._last_fps_update = time.time()

    def start(self) -> bool:
        """Start pose tracking worker."""
        if self.thread and self.thread.is_alive():
            return True
            
        # Initialize camera with optimized settings
        self.cap = cv2.VideoCapture(self.cam_index)
        if not self.cap.isOpened():
            return False
            
        # OPTIMIZED camera configuration
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # CRITICAL: Reduce buffer for real-time
        
        self.running.set()
        self.thread = Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        """Stop pose tracking worker."""
        self.running.clear()
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_latest_data(self) -> PoseData:
        """Get latest pose data."""
        return self.latest_data

    def _worker_loop(self):
        """Main worker loop - OPTIMIZED for performance."""
        frame_skip = 0  # Skip frames if processing is too slow
        
        while self.running.is_set():
            start_time = time.time()
            
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            
            # PERFORMANCE: Skip frames if we're falling behind
            frame_skip += 1
            if frame_skip % 2 == 0:  # Process every other frame if needed
                continue
                
            # CRITICAL FIX: Flip frame vertically to correct inversion
            frame = cv2.flip(frame, 0)  # 0 = flip around x-axis (vertical flip)
            
            # Convert BGR to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # MediaPipe pose detection
            results = self.pose.process(rgb_frame)
            
            # Process results
            landmarks = None
            angles = None
            
            if results.pose_landmarks:
                # Extract landmarks (already corrected by frame flip)
                landmarks = [
                    (lm.x, lm.y, lm.z) 
                    for lm in results.pose_landmarks.landmark
                ]
                
                # Calculate key angles
                angles = self._calculate_angles(landmarks)
            
            # Calculate FPS
            process_time = time.time() - start_time
            fps = 1.0 / process_time if process_time > 0 else 0
            
            # Update latest data
            self.latest_data = PoseData(
                timestamp=time.time(),
                landmarks=landmarks,
                angles=angles,
                frame_available=True,
                fps=fps
            )
            
            # Performance throttling - don't exceed target FPS
            target_frame_time = 1.0 / self.target_fps
            sleep_time = target_frame_time - process_time
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _calculate_angles(self, landmarks: List[Tuple[float, float, float]]) -> Dict[str, float]:
        """Calculate joint angles from pose landmarks."""
        if len(landmarks) < 33:  # MediaPipe has 33 pose landmarks
            return {}
        
        angles = {}
        
        try:
            # Hip angle (left side) - landmarks 23, 25, 27
            left_hip = np.array([landmarks[23][0], landmarks[23][1]])
            left_knee = np.array([landmarks[25][0], landmarks[25][1]]) 
            left_ankle = np.array([landmarks[27][0], landmarks[27][1]])
            angles['left_hip'] = self._angle_between_points(left_hip, left_knee, left_ankle)
            
            # Hip angle (right side) - landmarks 24, 26, 28
            right_hip = np.array([landmarks[24][0], landmarks[24][1]])
            right_knee = np.array([landmarks[26][0], landmarks[26][1]])
            right_ankle = np.array([landmarks[28][0], landmarks[28][1]])
            angles['right_hip'] = self._angle_between_points(right_hip, right_knee, right_ankle)
            
            # Knee angles
            # Left knee - landmarks 23, 25, 27 (hip, knee, ankle)
            angles['left_knee'] = self._angle_between_points(
                left_hip, left_knee, left_ankle
            )
            
            # Right knee
            angles['right_knee'] = self._angle_between_points(
                right_hip, right_knee, right_ankle
            )
            
        except (IndexError, ValueError):
            # Handle calculation errors gracefully
            pass
            
        return angles

    def _angle_between_points(self, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> float:
        """Calculate angle between three points."""
        try:
            # Vectors from p2 to p1 and p2 to p3
            v1 = p1 - p2
            v2 = p3 - p2
            
            # Calculate angle using dot product
            cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
            cos_angle = np.clip(cos_angle, -1.0, 1.0)  # Clamp to valid range
            angle = np.arccos(cos_angle)
            
            return np.degrees(angle)
        except (ValueError, ZeroDivisionError):
            return 0.0

    def get_display_frame(self) -> Optional[np.ndarray]:
        """Get current frame for display purposes."""
        if not self.cap:
            return None
            
        ret, frame = self.cap.read()
        if not ret:
            return None
            
        # CRITICAL: Apply same flip for display consistency
        frame = cv2.flip(frame, 0)
        
        # Process with MediaPipe for visualization
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_frame)
        
        if results.pose_landmarks:
            # Draw pose landmarks on frame
            self.mp_drawing.draw_landmarks(
                frame, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS,
                self.mp_drawing.DrawingSpec(color=(245,117,66), thickness=2, circle_radius=2),
                self.mp_drawing.DrawingSpec(color=(245,66,230), thickness=2, circle_radius=1)
            )
        
        return frame
