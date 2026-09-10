# Utility functions: put_latest, get_latest, etc.
# -*- coding: utf-8 -*-
"""
Queue and math utilities shared by workers and GUI.
"""
import math
import queue
import numpy as np

def put_latest(q: queue.Queue, item) -> None:
    """Non-blocking put that keeps only the most recent item (queue maxsize=1 recommended)."""
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
    """Drain the queue and return the last item, or default if empty."""
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
    Compute pelvic obliquity using the available landmark convention.

    MediaPipe uses landmarks 23/24 for left/right hip. The legacy MoveNet
    convention uses 11/12. Image coordinates have y pointing down, so y is
    inverted before computing the angle. Invalid landmarks return NaN rather
    than silently becoming a level pelvis.
    Normalize to [-90, 90] for tilt-like interpretation.
    """
    if landmarks_px is None:
        return float("nan")

    points = np.asarray(landmarks_px)
    if points.ndim != 2 or points.shape[1] < 2:
        return float("nan")
    if points.shape[0] >= 25:
        left_idx, right_idx = 23, 24
    elif points.shape[0] > 12:
        left_idx, right_idx = 11, 12
    else:
        return float("nan")

    xL, yL = points[left_idx, :2]
    xR, yR = points[right_idx, :2]
    if not np.all(np.isfinite([xL, yL, xR, yR])):
        return float("nan")

    vx = xR - xL
    vy = -(yR - yL)  # convert image y (down) to Cartesian y (up)
    ang = math.degrees(math.atan2(vy, vx))  # range (-180, 180]
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return ang