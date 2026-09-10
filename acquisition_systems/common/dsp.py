# -*- coding: utf-8 -*-
"""
Digital Signal Processing (DSP) functions for the sEMG pipeline.
"""

import numpy as np
from scipy import signal as scipy_signal

def apply_fft_notch(signal: np.ndarray, fs: float = 1000.0, target_freq: float = 60.0, bandwidth: float = 4.0) -> np.ndarray:
    """
    Applies a stable zero-phase notch filter.

    The original implementation zeroed FFT bins without a window. That made
    the result depend on record length and caused spectral leakage/ringing when
    the interference was not exactly bin-centred. IIR notch sections are
    numerically stable and work for arbitrary sample rates while preserving
    this function's public API.
    
    Args:
        signal (np.ndarray): The 1D array of EMG data.
        fs (float): Sampling frequency in Hz (default 1000.0).
        target_freq (float): The frequency to remove in Hz (default 60.0).
        bandwidth (float): Approximate notch width in Hz (default 4.0 Hz).
        
    Returns:
        np.ndarray: The filtered signal after inverse FFT.
    """
    values = np.asarray(signal, dtype=float)
    if values.size == 0:
        return values.copy()
    if fs <= 0 or target_freq <= 0 or bandwidth <= 0:
        raise ValueError("fs, target_freq, and bandwidth must be positive")
    if values.ndim != 1:
        raise ValueError("signal must be one-dimensional")
    if not np.all(np.isfinite(values)):
        raise ValueError("signal must contain only finite values")

    sections = []
    nyquist = fs / 2.0
    for harmonic in range(1, int(nyquist // target_freq) + 1):
        frequency = target_freq * harmonic
        if frequency >= nyquist:
            break
        q = max(frequency / bandwidth, 0.5)
        b, a = scipy_signal.iirnotch(frequency, q, fs=fs)
        sections.append(scipy_signal.tf2sos(b, a))

    if not sections:
        return values.copy()

    sos = np.vstack(sections)
    if values.size < 8:
        return scipy_signal.sosfilt(sos, values)
    try:
        return scipy_signal.sosfiltfilt(sos, values)
    except ValueError:
        # Very short recordings cannot satisfy filtfilt's padding rule.
        return scipy_signal.sosfilt(sos, values)
