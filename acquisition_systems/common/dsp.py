# -*- coding: utf-8 -*-
"""
Digital Signal Processing (DSP) functions for the sEMG pipeline.
"""

import numpy as np
from scipy import fft

def apply_fft_notch(signal: np.ndarray, fs: float = 1000.0, target_freq: float = 60.0, bandwidth: float = 4.0) -> np.ndarray:
    """
    Applies a notch filter using Fast Fourier Transform (FFT) and inverse FFT.
    
    Args:
        signal (np.ndarray): The 1D array of EMG data.
        fs (float): Sampling frequency in Hz (default 1000.0).
        target_freq (float): The frequency to remove in Hz (default 60.0).
        bandwidth (float): The bandwidth around the target frequency to zero out (default 4.0 Hz).
        
    Returns:
        np.ndarray: The filtered signal after inverse FFT.
    """
    if len(signal) == 0:
        return signal

    # 1. Compute the Real Fast Fourier Transform (FFT)
    N = len(signal)
    yf = fft.rfft(signal)
    xf = fft.rfftfreq(N, 1.0 / fs)

    # 2. Find the indices corresponding to the 60 Hz target frequency
    # We zero out a small band around 60 Hz to ensure we catch it
    idx_to_zero = np.where((xf >= target_freq - bandwidth/2.0) & (xf <= target_freq + bandwidth/2.0))[0]
    
    # Also remove harmonics of the powerline frequency (120 Hz, 180 Hz, etc.)
    for harmonic in range(2, int((fs/2.0) // target_freq) + 1):
        h_freq = target_freq * harmonic
        idx_h = np.where((xf >= h_freq - bandwidth/2.0) & (xf <= h_freq + bandwidth/2.0))[0]
        idx_to_zero = np.concatenate((idx_to_zero, idx_h))

    # 3. Remove the 60 Hz component (set bins to exactly zero)
    yf[idx_to_zero] = 0.0 + 0.0j

    # 4. Apply Inverse Fast Fourier Transform (iFFT)
    filtered_signal = fft.irfft(yf, n=N)
    
    return filtered_signal
