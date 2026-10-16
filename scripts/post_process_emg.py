"""
Post-acquisition sEMG processing for a saved session (paper Sec. 3.3):
alias-aware FFT notch -> 6th-order Butterworth low-pass (10 Hz) -> Hilbert envelope.

Usage:
  python scripts/post_process_emg.py [path_to_csv] [--no-show] [--png out.png]

Without a path, the newest ``*_emg.csv`` (native-rate EMG) in sessions/ is used.
A merged ``<base>.csv`` is resolved to its ``<base>_emg.csv`` sibling when present.
"""
import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acquisition_systems.postprocess import process_emg_csv


def get_latest_session_csv(sessions_dir: str):
    """Most recent native EMG CSV (falls back to any unprocessed CSV for old sessions)."""
    files = glob.glob(os.path.join(sessions_dir, "**", "*_emg.csv"), recursive=True)
    if not files:
        files = [f for f in glob.glob(os.path.join(sessions_dir, "**", "*.csv"), recursive=True)
                 if "_processed" not in f and not f.endswith(("_cop.csv", "_pose.csv"))]
    return max(files, key=os.path.getmtime) if files else None


def post_process_emg(csv_path: str, show_plot: bool = True, png_path: str = None) -> str:
    """Process ``csv_path``; optionally save a PNG and/or show it in a window."""
    if show_plot and not png_path:
        png_path = os.path.splitext(csv_path)[0] + "_processed.png"
    out_path = process_emg_csv(csv_path, png_path=png_path)
    if show_plot and png_path:
        try:
            import matplotlib.pyplot as plt
            import matplotlib.image as mpimg
            plt.imshow(mpimg.imread(png_path)); plt.axis("off"); plt.show()
        except Exception as exc:
            print(f"Cannot open a window ({exc}); figure saved to {png_path}")
    return out_path


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    sessions_dir = os.path.join(base_dir, "sessions")
    show_plot = "--no-show" not in sys.argv
    png = None
    args = sys.argv[1:]
    if "--png" in args:
        i = args.index("--png")
        png = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    positional = [a for a in args if not a.startswith("--")]
    target_csv = positional[0] if positional else get_latest_session_csv(sessions_dir)

    if target_csv and os.path.exists(target_csv):
        post_process_emg(target_csv, show_plot=show_plot, png_path=png)
    else:
        print("No CSV files found in the sessions directory to process.")
        print("Usage: python post_process_emg.py [path_to_csv] [--no-show] [--png out.png]")
