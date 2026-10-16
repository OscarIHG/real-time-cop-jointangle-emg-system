# -*- coding: utf-8 -*-
"""
Post-acquisition sEMG processing (paper Sec. 3.3):
  notch (already in emg_notch_V) -> 6th-order Butterworth low-pass at 10 Hz
  -> Hilbert amplitude envelope.

Works on the native-rate ``<base>_emg.csv``. A merged ``<base>.csv`` is
accepted for older sessions; when the matching ``_emg.csv`` exists next to it,
that file is used instead, because merged rows may repeat EMG samples.
"""
import os
from typing import Optional

import numpy as np

from acquisition_systems.common.dsp import fft_notch, hilbert_envelope, lowpass_filter


def resolve_emg_csv(csv_path: str) -> str:
    if csv_path.endswith("_emg.csv"):
        return csv_path
    candidate = csv_path[:-4] + "_emg.csv" if csv_path.endswith(".csv") else csv_path + "_emg.csv"
    return candidate if os.path.exists(candidate) else csv_path


def process_emg_csv(csv_path: str, png_path: Optional[str] = None, cutoff_hz: float = 10.0,
                    order: int = 6, powerline_hz: float = 60.0, verbose: bool = True) -> str:
    import pandas as pd

    source = resolve_emg_csv(csv_path)
    if verbose:
        print(f"Loading data from: {source}")
    df = pd.read_csv(source)
    if "time_s" not in df.columns or "emg_V" not in df.columns:
        raise ValueError("CSV does not contain 'time_s' and 'emg_V' columns")

    columns = ["time_s", "emg_V"] + (["emg_notch_V"] if "emg_notch_V" in df.columns else [])
    df_emg = df[columns].dropna(subset=["time_s", "emg_V"]).copy()
    t = df_emg["time_s"].to_numpy(dtype=float)
    raw = df_emg["emg_V"].to_numpy(dtype=float)
    if len(raw) < 8:
        raise ValueError("at least 8 EMG samples are required for processing")

    dt = np.diff(t)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if dt.size == 0:
        raise ValueError("EMG timestamps must be strictly increasing")
    fs = 1.0 / float(np.median(dt))
    if verbose:
        print(f"Detected Sampling Frequency (fs): {fs:.2f} Hz")
    if fs <= 2.0 * cutoff_hz:
        raise ValueError(f"detected fs={fs:.2f} Hz is too low for a {cutoff_hz} Hz low-pass")

    if "emg_notch_V" in df_emg.columns and df_emg["emg_notch_V"].notna().all():
        notch = df_emg["emg_notch_V"].to_numpy(dtype=float)
    else:
        notch = fft_notch(raw, fs, powerline_hz)

    smoothed = lowpass_filter(notch, fs, cutoff_hz, order)   # 6th order, zero phase
    envelope = hilbert_envelope(smoothed)

    df_emg["emg_notch_V"] = notch
    df_emg["emg_smoothed"] = smoothed
    df_emg["emg_envelope"] = envelope
    root, _ = os.path.splitext(source)
    out_path = root + "_processed.csv"
    df_emg.to_csv(out_path, index=False)
    if verbose:
        print(f"Saved processed data to: {out_path}")

    if png_path:
        save_plot(t, raw, notch, smoothed, envelope, fs, png_path)
        if verbose:
            print(f"Saved figure to: {png_path}")
    return out_path


def save_plot(t, raw, notch, smoothed, envelope, fs, png_path: str) -> None:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    fig = Figure(figsize=(11, 6), dpi=100)
    FigureCanvasAgg(fig)
    ax1, ax2 = fig.subplots(2, 1)
    ax1.plot(t, raw, color="0.6", lw=0.8, label="Raw (ESP32)")
    ax1.plot(t, notch, color="#0072B2", lw=0.8, label="Notch (alias-aware FFT)")
    ax1.plot(t, smoothed, color="#D55E00", lw=1.5, label="Butterworth 6th, 10 Hz")
    ax1.plot(t, envelope, color="#009E73", lw=1.5, label="Hilbert envelope")
    ax1.set_xlabel("Time [s]"); ax1.set_ylabel("Amplitude [V]"); ax1.legend(loc="upper right", fontsize=8)
    ax1.set_title("Abdominal EMG - post-acquisition processing")
    for sig, label, color in ((raw, "Raw", "0.6"), (notch, "Notch", "#0072B2")):
        x = np.asarray(sig) - np.mean(sig)
        spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) / max(1, x.size)
        f = np.fft.rfftfreq(x.size, 1.0 / fs)
        ax2.semilogy(f, spec + 1e-9, color=color, lw=0.8, label=label)
    ax2.set_xlabel("Frequency [Hz]"); ax2.set_ylabel("|X(f)|"); ax2.legend(fontsize=8)
    ax2.set_title("Spectrum (60 Hz interference appears at its alias)")
    fig.tight_layout()
    fig.savefig(png_path)
