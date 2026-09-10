import os
import glob
import sys
import pandas as pd
import numpy as np
from scipy import signal

from acquisition_systems.common.dsp import apply_fft_notch
from pathlib import Path

def get_latest_session_csv(sessions_dir: str) -> str:
    """Finds the most recently created CSV file in the sessions directory structure."""
    search_pattern = os.path.join(sessions_dir, "**", "*.csv")
    csv_files = glob.glob(search_pattern, recursive=True)
    
    # Exclude files that are already processed
    csv_files = [f for f in csv_files if "_processed" not in f]
    
    if not csv_files:
        return None
        
    latest_file = max(csv_files, key=os.path.getctime)
    return latest_file

def post_process_emg(csv_path: str, show_plot: bool = True) -> str:
    """
    Applies the post-acquisition DSP pipeline to a saved session CSV.
    Applies the following DSP steps:
    1. 6th-order Butterworth low-pass filter (10 Hz).
    2. Hilbert transform to calculate the amplitude envelope.
    """
    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)
    
    if 'time_s' not in df.columns or 'emg_V' not in df.columns:
        raise ValueError("CSV does not contain 'time_s' and 'emg_V' columns")

    # Drop NaNs if EMG was sampled slower than other sensors in merged CSV
    columns = ["time_s", "emg_V"]
    if "emg_notch_V" in df.columns:
        columns.append("emg_notch_V")
    df_emg = df[columns].dropna(subset=["time_s", "emg_V"])
    t = df_emg['time_s'].to_numpy(dtype=float)
    raw_signal = df_emg['emg_V'].to_numpy(dtype=float)
    if len(raw_signal) < 8:
        raise ValueError("at least 8 EMG samples are required for processing")
    
    dt_values = np.diff(t)
    valid_dt = dt_values[np.isfinite(dt_values) & (dt_values > 0)]
    if valid_dt.size == 0:
        raise ValueError("EMG timestamps must be strictly increasing")
    fs = 1.0 / float(np.median(valid_dt))
    print(f"Detected Sampling Frequency (fs): {fs:.2f} Hz")
    
    # 1. Notch the recorded EMG using the detected native rate. Older CSVs do
    # not contain this column, so calculate it here for backwards compatibility.
    if "emg_notch_V" in df_emg.columns:
        notch_signal = df_emg["emg_notch_V"].to_numpy(dtype=float)
    else:
        notch_signal = apply_fft_notch(raw_signal, fs=fs, target_freq=60.0)

    # 2. 6th-order Butterworth low-pass filter (10 Hz), represented as SOS to
    # avoid unstable high-order polynomial coefficients.
    print("Applying stable 6th-order Butterworth low-pass filter (10 Hz)...")
    if fs <= 20.0:
        raise ValueError(f"detected fs={fs:.2f} Hz is too low for a 10 Hz low-pass")
    sos = signal.butter(6, 10.0, btype='low', fs=fs, output='sos')
    try:
        smoothed_signal = signal.sosfiltfilt(sos, notch_signal)
    except ValueError:
        smoothed_signal = signal.sosfilt(sos, notch_signal)
    
    # 3. Hilbert Transform for amplitude envelope
    print("Applying Hilbert Transform to extract amplitude envelope...")
    analytic_signal = signal.hilbert(smoothed_signal)
    amplitude_envelope = np.abs(analytic_signal)
    
    # Add to dataframe
    df_emg['emg_notch_V'] = notch_signal
    df_emg['emg_smoothed'] = smoothed_signal
    df_emg['emg_envelope'] = amplitude_envelope
    
    # Save to a new CSV
    out_path = csv_path.replace(".csv", "_processed.csv")
    df_emg.to_csv(out_path, index=False)
    print(f"Saved processed data to: {out_path}")
    
    # --- PyQtGraph Visualization ---
    if not show_plot:
        return out_path

    import pyqtgraph as pg
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        
    win = pg.GraphicsLayoutWidget(show=True, title="sEMG Post-Acquisition Processing")
    win.resize(1000, 600)
    win.setWindowTitle('sEMG Signal Processing')
    
    # Create a single plot area
    p1 = win.addPlot(title="Raw Hardware Signal vs Filtered vs Envelope")
    p1.setLabel('bottom', "Time", units='s')
    p1.setLabel('left', "Amplitude", units='V')
    p1.addLegend()
    p1.showGrid(x=True, y=True)
    
    # Plot the three signals
    p1.plot(t, raw_signal, pen=pg.mkPen(color=(100, 100, 100, 150), width=1), name="Hardware Output (Raw)")
    p1.plot(t, smoothed_signal, pen=pg.mkPen(color=(0, 114, 178), width=2), name="Butterworth Low-pass (10 Hz)")
    p1.plot(t, amplitude_envelope, pen=pg.mkPen(color=(213, 94, 0), width=3), name="Hilbert Amplitude Envelope")
    
    print("Opening PyQtGraph window. Close the window to exit the script.")
    if sys.flags.interactive != 1:
        QtWidgets.QApplication.instance().exec_()
    return out_path

if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    sessions_dir = os.path.join(base_dir, "sessions")
    
    target_csv = None
    if len(sys.argv) > 1:
        target_csv = sys.argv[1]
    else:
        target_csv = get_latest_session_csv(sessions_dir)
        
    if target_csv and os.path.exists(target_csv):
        post_process_emg(target_csv, show_plot="--no-show" not in sys.argv)
    else:
        print("No CSV files found in the sessions directory to process.")
        print("Usage: python post_process_emg.py [path_to_csv]")
