# -*- coding: utf-8 -*-
"""
Digital Signal Processing (DSP) functions for the sEMG pipeline.

Paper pipeline:
  * Real time:        60 Hz notch via FFT -> remove component -> inverse FFT.
  * Post-acquisition: 6th-order Butterworth low-pass (10 Hz) -> Hilbert envelope.

Aliasing note: the sEMG is sampled at ~100 Hz, so Nyquist is 50 Hz and a 60 Hz
power-line tone cannot exist in the digital spectrum. Once sampled it folds to
|60 - 100| = 40 Hz (sin(2*pi*0.6*n) == -sin(2*pi*0.4*n)). Every notch here
therefore targets the *aliased* frequency computed by ``alias_frequency``.
"""

from typing import List, Optional, Tuple

import numpy as np
from scipy import signal as scipy_signal

from acquisition_systems.common.utils import RingBuffer


def alias_frequency(freq: float, fs: float) -> float:
    """Frequency (0..fs/2) at which a real tone of ``freq`` appears when sampled at ``fs``."""
    if fs <= 0:
        raise ValueError("fs must be positive")
    return float(abs(freq - fs * round(freq / fs)))


def powerline_targets(fs: float, f0: float = 60.0, harmonics: int = 1, min_hz: float = 0.5) -> List[float]:
    """Aliased power-line frequencies to remove (DC aliases are skipped)."""
    targets: List[float] = []
    for k in range(1, max(1, int(harmonics)) + 1):
        f = alias_frequency(f0 * k, fs)
        if f < min_hz or f > fs / 2.0:
            continue
        if all(abs(f - t) > 1e-6 for t in targets):
            targets.append(f)
    return targets


def _validate(signal: np.ndarray, fs: float) -> np.ndarray:
    values = np.asarray(signal, dtype=float)
    if fs <= 0:
        raise ValueError("fs must be positive")
    if values.ndim != 1:
        raise ValueError("signal must be one-dimensional")
    if values.size and not np.all(np.isfinite(values)):
        raise ValueError("signal must contain only finite values")
    return values


def _bin_centred_length(n: int, fs: float, targets: List[float], max_trim: int = 200) -> int:
    """Largest length <= n for which every target falls exactly on an FFT bin."""
    for length in range(n, max(8, n - max_trim) - 1, -1):
        if all(abs(t * length / fs - round(t * length / fs)) < 1e-6 for t in targets):
            return length
    return n


def _notch_block(x: np.ndarray, fs: float, targets: List[float], bandwidth_hz: float) -> np.ndarray:
    n = x.size
    # Remove the straight line joining the end points: the periodic extension
    # assumed by the FFT becomes continuous, so the record edges do not leak
    # into the notch band (the source of edge spikes with naive bin zeroing).
    line = x[0] + (x[-1] - x[0]) * np.arange(n) / (n - 1)
    spectrum = np.fft.rfft(x - line)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    half = bandwidth_hz / 2.0
    mask = np.ones_like(freqs)
    for target in targets:
        d = np.abs(freqs - target)
        gain = np.where(d <= half, 0.0, 1.0)
        ramp = (d > half) & (d < 2.0 * half)
        gain[ramp] = 0.5 * (1.0 - np.cos(np.pi * (d[ramp] - half) / half))   # raised-cosine edges
        mask = np.minimum(mask, gain)
    return np.fft.irfft(spectrum * mask, n=n) + line


def fft_notch(
    signal: np.ndarray,
    fs: float,
    f0: float = 60.0,
    bandwidth_hz: float = 2.0,
    harmonics: int = 1,
) -> np.ndarray:
    """
    Power-line notch implemented as in the paper: FFT -> remove -> inverse FFT.

    Two details make it artefact-free at the record edges (which is where the
    newest samples of a real-time display live):
      * the analysis length is chosen so the (aliased) interference falls
        exactly on an FFT bin (at fs=100 Hz the 40 Hz alias needs a multiple
        of 5 samples); a stationary tone then has no spectral leakage;
      * the end-point line is removed before the FFT and restored after it.
    A raised-cosine mask replaces hard bin zeroing to avoid Gibbs ringing.
    """
    values = _validate(signal, fs)
    if bandwidth_hz <= 0:
        raise ValueError("bandwidth_hz must be positive")
    n = values.size
    targets = powerline_targets(fs, f0, harmonics)
    if n < 8 or not targets:
        return values.copy()

    length = _bin_centred_length(n, fs, targets)
    if length == n:
        return _notch_block(values, fs, targets, bandwidth_hz)
    out = np.empty(n)
    out[n - length:] = _notch_block(values[n - length:], fs, targets, bandwidth_hz)
    out[:n - length] = _notch_block(values[:length], fs, targets, bandwidth_hz)[:n - length]
    return out


def apply_fft_notch(signal: np.ndarray, fs: float = 1000.0, target_freq: float = 60.0, bandwidth: float = 4.0) -> np.ndarray:
    """Backwards-compatible name for :func:`fft_notch` (alias-aware FFT notch)."""
    return fft_notch(signal, fs=fs, f0=target_freq, bandwidth_hz=bandwidth)


def iir_notch_sos(fs: float, f0: float = 60.0, bandwidth_hz: float = 2.0, harmonics: int = 1) -> Optional[np.ndarray]:
    """Second-order notch sections at the aliased power-line frequencies."""
    sections = []
    for target in powerline_targets(fs, f0, harmonics):
        if target >= fs / 2.0:
            continue  # iirnotch requires 0 < w0 < Nyquist
        q = max(target / bandwidth_hz, 0.5)
        b, a = scipy_signal.iirnotch(target, q, fs=fs)
        sections.append(scipy_signal.tf2sos(b, a))
    return np.vstack(sections) if sections else None


class StreamingIIRNotch:
    """Causal notch with persistent state: O(new samples) per call, no edge effects."""

    def __init__(self, fs: float, f0: float = 60.0, bandwidth_hz: float = 2.0, harmonics: int = 1):
        self.sos = iir_notch_sos(fs, f0, bandwidth_hz, harmonics)
        self._zi: Optional[np.ndarray] = None

    def reset(self) -> None:
        self._zi = None

    def process(self, chunk: np.ndarray) -> np.ndarray:
        x = np.asarray(chunk, dtype=float)
        if self.sos is None or x.size == 0:
            return x.copy()
        if self._zi is None:
            # Start in steady state for the first value to avoid a turn-on transient.
            self._zi = scipy_signal.sosfilt_zi(self.sos) * x[0]
        y, self._zi = scipy_signal.sosfilt(self.sos, x, zi=self._zi)
        return y


class RealtimeEmgFilter:
    """
    Fixed-size display filter for the GUIs.

    ``method="fft"`` recomputes the paper's FFT notch over a fixed window on
    every call (constant cost, independent of recording length).
    ``method="iir"`` filters only the new samples with a streaming notch.
    """

    def __init__(self, fs: float, window_s: float = 5.0, method: str = "fft",
                 f0: float = 60.0, bandwidth_hz: float = 2.0, harmonics: int = 1):
        if method not in ("fft", "iir"):
            raise ValueError("method must be 'fft' or 'iir'")
        self.fs = float(fs)
        self.method = method
        self.f0, self.bandwidth_hz, self.harmonics = f0, bandwidth_hz, harmonics
        capacity = max(16, int(round(window_s * fs)))
        self._t = RingBuffer(capacity)
        self._raw = RingBuffer(capacity)
        self._filt = RingBuffer(capacity)
        self._iir = StreamingIIRNotch(fs, f0, bandwidth_hz, harmonics) if method == "iir" else None

    def clear(self) -> None:
        self._t.clear(); self._raw.clear(); self._filt.clear()
        if self._iir is not None:
            self._iir.reset()

    def extend(self, times: np.ndarray, values: np.ndarray) -> None:
        values = np.asarray(values, dtype=float)
        if values.size == 0:
            return
        self._t.extend(times)
        self._raw.extend(values)
        if self._iir is not None:
            self._filt.extend(self._iir.process(values))

    def window(self) -> Tuple[np.ndarray, np.ndarray]:
        t = self._t.values()
        if self._iir is not None:
            return t, self._filt.values()
        raw = self._raw.values()
        if raw.size < 8:
            return t, raw
        return t, fft_notch(raw, self.fs, self.f0, self.bandwidth_hz, self.harmonics)


def butter_lowpass_sos(fs: float, cutoff_hz: float = 10.0, order: int = 6) -> np.ndarray:
    """6th-order Butterworth low-pass (paper) as numerically stable SOS sections."""
    if cutoff_hz >= fs / 2.0:
        raise ValueError(f"cutoff {cutoff_hz} Hz must be below Nyquist ({fs / 2.0:.2f} Hz)")
    return scipy_signal.butter(order, cutoff_hz, btype="low", fs=fs, output="sos")


def lowpass_filter(x: np.ndarray, fs: float, cutoff_hz: float = 10.0, order: int = 6,
                   zero_phase: bool = True) -> np.ndarray:
    """
    Apply the Butterworth low-pass. ``zero_phase`` (default) runs it forward and
    backward so smoothing introduces no lag relative to CoP/angle; the magnitude
    response is then squared (-6 dB at the cutoff instead of -3 dB).
    """
    values = _validate(x, fs)
    sos = butter_lowpass_sos(fs, cutoff_hz, order)
    if not zero_phase:
        return scipy_signal.sosfilt(sos, values, zi=scipy_signal.sosfilt_zi(sos) * values[0])
    try:
        return scipy_signal.sosfiltfilt(sos, values)
    except ValueError:
        return scipy_signal.sosfilt(sos, values)


def hilbert_envelope(x: np.ndarray, pad_fraction: float = 0.1) -> np.ndarray:
    """Amplitude envelope |x + j*H{x}| with mirror padding to suppress edge artefacts."""
    values = np.asarray(x, dtype=float)
    n = values.size
    if n < 4:
        return np.abs(values)
    pad = min(n - 1, max(1, int(pad_fraction * n)))
    padded = np.pad(values, pad, mode="reflect")
    return np.abs(scipy_signal.hilbert(padded))[pad:pad + n]
