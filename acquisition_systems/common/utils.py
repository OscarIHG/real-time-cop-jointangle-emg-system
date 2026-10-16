# Utility functions: queues, ring buffers, rate meters and biomechanics math.
# -*- coding: utf-8 -*-
"""
Queue, buffer and math utilities shared by workers, the session coordinator
and the GUIs.
"""
import math
import queue
import threading
import time
from collections import deque
from typing import Optional, Sequence, Tuple

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


def put_counting(q: queue.Queue, item) -> bool:
    """Put without blocking; on overflow drop the OLDEST item. Returns False if a sample was dropped."""
    try:
        q.put_nowait(item)
        return True
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass
        return False


def drain(q: queue.Queue, limit: int = 100_000) -> list:
    """Return every item currently in the queue (bounded)."""
    items = []
    for _ in range(limit):
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            break
    return items


class RingBuffer:
    """Fixed-capacity float buffer backed by numpy (no per-tick Python list copies)."""

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self._data = np.full(self.capacity, np.nan, dtype=float)
        self._size = 0
        self._head = 0  # next write position

    def clear(self) -> None:
        self._size = 0
        self._head = 0

    def __len__(self) -> int:
        return self._size

    def append(self, value: float) -> None:
        self._data[self._head] = value
        self._head = (self._head + 1) % self.capacity
        self._size = min(self._size + 1, self.capacity)

    def extend(self, values) -> None:
        values = np.asarray(values, dtype=float).ravel()
        if values.size >= self.capacity:
            self._data[:] = values[-self.capacity:]
            self._head = 0
            self._size = self.capacity
            return
        end = self._head + values.size
        if end <= self.capacity:
            self._data[self._head:end] = values
        else:
            split = self.capacity - self._head
            self._data[self._head:] = values[:split]
            self._data[:end - self.capacity] = values[split:]
        self._head = end % self.capacity
        self._size = min(self._size + values.size, self.capacity)

    def values(self) -> np.ndarray:
        """Chronologically ordered copy of the stored values."""
        if self._size < self.capacity:
            return self._data[:self._size].copy()
        return np.concatenate((self._data[self._head:], self._data[:self._head]))

    def last(self, default: float = float("nan")) -> float:
        if self._size == 0:
            return default
        return float(self._data[(self._head - 1) % self.capacity])


class RateMeter:
    """Thread-safe event-rate estimate over a sliding time window."""

    def __init__(self, window_s: float = 2.0):
        self.window_s = float(window_s)
        self._times: deque = deque()
        self._lock = threading.Lock()
        self.total = 0

    def tick(self, n: int = 1, t: Optional[float] = None) -> None:
        t = time.perf_counter() if t is None else t
        with self._lock:
            self.total += n
            for _ in range(n):
                self._times.append(t)
            cutoff = t - self.window_s
            while self._times and self._times[0] < cutoff:
                self._times.popleft()

    def rate(self) -> float:
        with self._lock:
            now = time.perf_counter()
            while self._times and self._times[0] < now - self.window_s:
                self._times.popleft()
            if len(self._times) < 2:
                return 0.0
            span = max(now - self._times[0], 1e-9)
            return (len(self._times) - 1) / span


def cop_from_forces(
    forces: Sequence[float],
    x_dist: float,
    y_dist: float,
    min_fz: float = 0.0,
) -> Tuple[float, float, float]:
    """
    Centre of pressure exactly as Eqs. (1) and (2) of the paper:

        Fz   = F1 + F2 + F3 + F4
        CoP1 = (x/2) * [(F1 + F4) - (F2 + F3)] / Fz      (paper: CoP_ap)
        CoP2 = (y/2) * [(F3 + F4) - (F1 + F2)] / Fz      (paper: CoP_ml)

    The *whole* force difference is divided by Fz; the printed equations have
    a bracket typo that divides only the second term. F1..F4 are channels
    CH0..CH3 (CH0 top-left, CH1 top-right, CH2 bottom-right, CH3 bottom-left in
    Fig. 1A), and x/y are the distances between load-cell centres. CoP1 lies
    on the long plate axis and CoP2 on the short one. Note that the paper
    defines x along the ML axis, so CoP1 is mediolateral despite its "ap"
    subscript.

    Returns (CoP1, CoP2, Fz); the CoP is NaN when Fz < ``min_fz``.
    """
    f1, f2, f3, f4 = (float(v) for v in forces)
    fz = f1 + f2 + f3 + f4
    if not math.isfinite(fz) or fz < max(min_fz, 1e-12):
        return float("nan"), float("nan"), fz
    cop1 = (x_dist / 2.0) * (((f1 + f4) - (f2 + f3)) / fz)
    cop2 = (y_dist / 2.0) * (((f3 + f4) - (f1 + f2)) / fz)
    return cop1, cop2, fz


def pelvic_obliquity_deg_from_landmarks(
    landmarks_px: np.ndarray,
    visibility: Optional[np.ndarray] = None,
    min_visibility: float = 0.0,
) -> float:
    """
    Pelvic obliquity: angle of the vector from the left hip (MediaPipe 23) to
    the right hip (24) relative to the horizontal; 0 deg = level hips.

    Image coordinates have y pointing down, so y is inverted before atan2 and
    the result is folded to [-90, 90] (line inclination). For a frontal,
    non-mirrored view a positive angle means the subject's left hip (23) is
    higher than the right hip (24). The legacy MoveNet convention (11/12) is
    still accepted. Invalid or poorly visible hips return NaN instead of a
    misleading level pelvis.
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

    if visibility is not None and min_visibility > 0:
        vis = np.asarray(visibility, dtype=float)
        if vis.shape[0] > right_idx and (
            not vis[left_idx] >= min_visibility or not vis[right_idx] >= min_visibility
        ):
            return float("nan")

    xL, yL = points[left_idx, :2]
    xR, yR = points[right_idx, :2]
    if not np.all(np.isfinite([xL, yL, xR, yR])):
        return float("nan")

    vx = xR - xL
    vy = -(yR - yL)  # convert image y (down) to Cartesian y (up)
    if vx == 0 and vy == 0:
        return float("nan")
    ang = math.degrees(math.atan2(vy, vx))  # range (-180, 180]
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return ang
