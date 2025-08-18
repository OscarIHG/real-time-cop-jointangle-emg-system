# Utility functions: put_latest, get_latest, etc.
# -*- coding: utf-8 -*-
"""
Queue and math utilities shared by workers and GUI.
"""
import math
import queue
import numpy as np

def put_latest(q: queue.Queue, item) -> None:
    """Non-blocking put that always keeps only the latest item (queue maxsize=1 recommended)."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except Exception:
            pass
        try:
            q.put_nowait(item)
        except Exception:
            pass

def get_latest(q: queue.Queue, default=None):
    """Drain queue and return last item, or default if empty."""
    last = default
    got = False
    while True:
        try:
            last = q.get_nowait()
            got = True
        except Exception:
            break
    return last if got else default

def pelvic_obliquity_deg_from_landmarks(landmarks_px: np.ndarray) -> float:
    """
    Compute angle of vector 23->24 relative to +x, with y up (invert image y).
    Normalize to [-90, 90] for tilt-like interpretation.
    """
    if landmarks_px is None or landmarks_px.shape[0] <= 24:
        return float("nan")
    xL, yL = landmarks_px[23, 0], landmarks_px[23, 1]
    xR, yR = landmarks_px[24, 0], landmarks_px[24, 1]
    vx = xR - xL
    vy = -(yR - yL)  # image y down -> Cartesian y up
    ang = math.degrees(math.atan2(vy, vx))  # (-180, 180]
    if ang > 90: ang -= 180
    if ang < -90: ang += 180
    return ang