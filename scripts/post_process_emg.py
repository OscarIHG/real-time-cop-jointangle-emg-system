import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from pathlib import Path
import sys

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

def post_process_emg(csv_path: str):
    """
    Applies the post-acquisition DSP pipeline to a saved session CSV.
    Methodology exactly matches the published paper:
    1. 6th-order Butterworth low-pass filter (10 Hz).
    2. Hilbert transform to calculate the amplitude envelope.
    """
    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)
    
    if 'time_s' not in df.columns or 'emg_V' not in df.columns:
        print("Error: CSV does not contain 'time_s' and 'emg_V' columns.")
        return

    # Drop NaNs if EMG was sampled slower than other sensors in merged CSV
    df_emg = df[['time_s', 'emg_V']].dropna()
    t = df_emg['time_s'].values
    raw_signal = df_emg['emg_V'].values
    
    # Calculate average sampling frequency from timestamps
    dt = np.mean(np.diff(t))
    fs = 1.0 / dt if dt > 0 else 1000.0
    print(f"Detected Sampling Frequency (fs): {fs:.2f} Hz")
    
    # 1. 6th-order Butterworth low-pass filter (10 Hz)
    print("Applying 6th-order Butterworth low-pass filter (10 Hz)...")
    b, a = signal.butter(6, 10.0, btype='low', fs=fs)
    smoothed_signal = signal.filtfilt(b, a, raw_signal)
    
    # 2. Hilbert Transform for amplitude envelope
    print("Applying Hilbert Transform to extract amplitude envelope...")
    analytic_signal = signal.hilbert(smoothed_signal)
    amplitude_envelope = np.abs(analytic_signal)
    
    # Add to dataframe
    df_emg['emg_smoothed'] = smoothed_signal
    df_emg['emg_envelope'] = amplitude_envelope
    
    # Save to a new CSV
    out_path = csv_path.replace(".csv", "_processed.csv")
    df_emg.to_csv(out_path, index=False)
    print(f"Saved processed data to: {out_path}")
    
    # Plotting
    plt.figure(figsize=(12, 6))
    plt.plot(t, raw_signal, label='Hardware Output (Raw)', alpha=0.5, color='gray')
    plt.plot(t, smoothed_signal, label='Butterworth Low-pass (10 Hz)', alpha=0.8, color='blue')
    plt.plot(t, amplitude_envelope, label='Hilbert Amplitude Envelope', linewidth=2, color='red')
    
    plt.title('sEMG Post-Acquisition Processing (Paper Methodology)')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    
    # Save plot next to the processed CSV
    plot_path = csv_path.replace(".csv", "_plot.png")
    plt.savefig(plot_path)
    print(f"Saved plot to: {plot_path}")
    plt.show()

if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    sessions_dir = os.path.join(base_dir, "sessions")
    
    target_csv = None
    if len(sys.argv) > 1:
        target_csv = sys.argv[1]
    else:
        target_csv = get_latest_session_csv(sessions_dir)
        
    if target_csv and os.path.exists(target_csv):
        post_process_emg(target_csv)
    else:
        print("No CSV files found in the sessions directory to process.")
        print("Usage: python post_process_emg.py [path_to_csv]")
