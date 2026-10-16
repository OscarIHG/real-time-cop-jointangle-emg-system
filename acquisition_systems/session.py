# -*- coding: utf-8 -*-
"""
AcquisitionSession: the central coordinator described in the paper (Sec. 3.1).

It owns the three acquisition workers (EMG, CoP, pose), routes every sample
into the Recorder, keeps fixed-size display buffers, measures real rates and
writes the dataset. It is GUI-agnostic: the PyQtGraph and Tkinter GUIs are
thin views on top of it, and ``python -m acquisition_systems.session`` runs
the same pipeline headless (useful over SSH).

Threading model: connect()/close()/export() block and should run off the GUI
thread; poll(), start_recording() and stop_recording() run on the GUI thread.
Workers only communicate through thread-safe queues, so no GUI toolkit is
ever called from a worker thread.
"""
import argparse
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

import numpy as np

from acquisition_systems.common.config import Config, config_to_dict, load_config
from acquisition_systems.common.dsp import RealtimeEmgFilter
from acquisition_systems.common.utils import RingBuffer, drain
from acquisition_systems.recorder import Recorder, RecordingSnapshot

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
FINISH_GRACE_S = 0.6  # keep draining in-flight samples (BT, inference latency) after t_end


def sessions_dir() -> str:
    path = os.path.join(REPO_ROOT, "sessions", datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(path, exist_ok=True)
    return path


def _git_revision() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=2)
        return out.stdout.strip() or None
    except Exception:
        return None


@dataclass
class LiveData:
    now: float
    emg_t: np.ndarray            # seconds relative to now (<= 0)
    emg_v: np.ndarray            # notch-filtered display window
    cop_xy: Optional[tuple]      # latest (x, y) or None when unloaded / no data
    cop_kg: float
    pose: Optional[object]       # newest PoseSample or None if nothing new
    angle_t: np.ndarray          # seconds since recording (or preview) start
    angle_v: np.ndarray
    new_emg: bool = False
    new_cop: bool = False
    state: str = "idle"          # idle | recording | finishing
    elapsed_s: float = 0.0
    duration_s: float = 0.0
    recording_done: bool = False  # True exactly once, when a recording completes
    rates: Dict[str, float] = field(default_factory=dict)


class AcquisitionSession:
    def __init__(self, cfg: Optional[Config] = None, emg_source: Optional[str] = None,
                 enable_emg: bool = True, enable_cop: bool = True, enable_pose: bool = True):
        self.cfg = cfg or load_config()
        if emg_source:
            self.cfg.emg_source = emg_source
        self.enabled = {"emg": enable_emg, "cop": enable_cop, "pose": enable_pose}
        self.emg = self.cop = self.pose = None
        self.errors: Dict[str, Optional[str]] = {}
        self.recorder = Recorder(
            self.cfg.recording_max_samples_per_stream, emg_fs=self.cfg.emg_sample_rate_hz,
            powerline_hz=self.cfg.emg_powerline_hz, notch_bandwidth_hz=self.cfg.emg_notch_bandwidth_hz,
            notch_harmonics=self.cfg.emg_notch_harmonics,
        )
        self.recorder.set_window(float("inf"))  # nothing is recorded until start_recording()
        self.emg_filter = RealtimeEmgFilter(
            self.cfg.emg_sample_rate_hz, self.cfg.emg_plot_window, self.cfg.emg_notch_method,
            self.cfg.emg_powerline_hz, self.cfg.emg_notch_bandwidth_hz, self.cfg.emg_notch_harmonics,
        )
        cap = int(max(60, self.cfg.angle_plot_window * max(self.cfg.cam_fps, 1)))
        self._ang_t = RingBuffer(cap)
        self._ang_v = RingBuffer(cap)
        self._cop_latest = None
        self._cop_kg = float("nan")
        self._display_origin = time.perf_counter()
        self.state = "idle"
        self.t0: Optional[float] = None
        self.t_end: Optional[float] = None
        self.duration_s = 0.0
        self._started_wall: Optional[str] = None
        self._lock = threading.Lock()

    # ---------- lifecycle ----------
    def connect(self) -> Dict[str, Optional[str]]:
        """Start all enabled workers in parallel. Returns {module: error or None}."""
        cfg = self.cfg
        results: Dict[str, Optional[str]] = {}

        def start_emg():
            from acquisition_systems.workers.emg import EMGWorker
            w = EMGWorker(cfg.emg_mac, cfg.emg_com_port, cfg.emg_rfcomm_channel, cfg.emg_vmin, cfg.emg_vmax,
                          start_token=cfg.emg_start_token, stop_token=cfg.emg_stop_token,
                          sample_rate_hz=cfg.emg_sample_rate_hz, source=cfg.emg_source,
                          connect_timeout_s=cfg.emg_connect_timeout_s)
            w.ALLOW_LF = cfg.emg_allow_lf
            w.start()
            if not w.wait_ready(cfg.emg_connect_timeout_s + 4.0):
                w.stop()
                raise RuntimeError(w.error or "EMG connection timed out")
            self.emg = w

        def start_cop():
            from acquisition_systems.workers.cop import CoPWorker
            w = CoPWorker(cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms,
                          flip_x=cfg.cop_flip_x, flip_y=cfg.cop_flip_y, swap_xy=cfg.cop_swap_xy,
                          bridge_gain=cfg.cop_bridge_gain, min_load_kg=cfg.cop_min_load_kg,
                          cell_capacity_kg=cfg.cop_cell_capacity_kg)
            w.start(tare=True)
            self.cop = w

        def start_pose():
            from acquisition_systems.workers.pose import PoseWorker
            w = PoseWorker(cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps, config=config_to_dict(cfg))
            w.start()
            self.pose = w

        def run(name, fn):
            try:
                fn()
                results[name] = None
            except Exception as exc:
                results[name] = f"{type(exc).__name__}: {exc}"
                print(f"[Session] {name} unavailable: {results[name]}")

        starters = {"emg": start_emg, "cop": start_cop, "pose": start_pose}
        threads = [threading.Thread(target=run, args=(n, f), daemon=True)
                   for n, f in starters.items() if self.enabled[n]]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.errors = results
        self._display_origin = time.perf_counter()
        return results

    def tare(self) -> dict:
        if self.cop is None:
            raise RuntimeError("force plate not connected")
        return self.cop.tare()

    def close(self) -> None:
        for w in (self.emg, self.cop, self.pose):
            if w is not None:
                try:
                    w.stop()
                except Exception as exc:
                    print(f"[Session] stop error: {exc}")
        self.emg = self.cop = self.pose = None

    # ---------- recording window ----------
    def start_recording(self, duration_s: float) -> None:
        self.duration_s = max(0.1, float(duration_s))
        self.t0 = time.perf_counter()
        self.t_end = self.t0 + self.duration_s
        self._started_wall = datetime.now().isoformat(timespec="seconds")
        self.recorder.clear()
        self.recorder.set_window(self.t0, self.t_end)
        self._ang_t.clear(); self._ang_v.clear()
        self.state = "recording"

    def stop_recording(self) -> None:
        if self.state == "recording":
            now = time.perf_counter()
            self.t_end = min(self.t_end, now)
            self.recorder.set_window(self.t0, self.t_end)
            self.state = "finishing"

    # ---------- polling (GUI thread) ----------
    def poll(self) -> LiveData:
        now = time.perf_counter()
        new_emg = new_cop = False
        if self.emg is not None:
            items = drain(self.emg.queue)
            if items:
                new_emg = True
                for s in items:
                    self.recorder.push_emg(s)
                self.emg_filter.extend(np.fromiter((s.t for s in items), float, len(items)),
                                       np.fromiter((s.value for s in items), float, len(items)))
        if self.cop is not None:
            items = drain(self.cop.queue)
            if items:
                new_cop = True
                for s in items:
                    self.recorder.push_cop(s)
                last = items[-1]
                self._cop_latest = (last.x, last.y) if np.isfinite(last.x) and np.isfinite(last.y) else None
                self._cop_kg = last.kg
        pose_latest = None
        if self.pose is not None:
            items = drain(self.pose.queue)
            if items:
                origin = self.t0 if self.state != "idle" and self.t0 else self._display_origin
                for s in items:
                    self.recorder.push_pose(s)
                    if self.state == "idle" or s.t <= (self.t_end or now):
                        self._ang_t.append(s.t - origin)
                        self._ang_v.append(s.angle_deg)
                pose_latest = items[-1]

        done = False
        if self.state == "recording" and now >= self.t_end:
            self.state = "finishing"
        if self.state == "finishing" and now >= self.t_end + FINISH_GRACE_S:
            self.state = "idle"
            done = True

        emg_t, emg_v = self.emg_filter.window()
        elapsed = 0.0
        if self.t0 is not None and self.state != "idle":
            elapsed = min(now, self.t_end) - self.t0
        return LiveData(
            now=now, emg_t=emg_t - now if emg_t.size else emg_t, emg_v=emg_v,
            cop_xy=self._cop_latest, cop_kg=self._cop_kg, pose=pose_latest,
            angle_t=self._ang_t.values(), angle_v=self._ang_v.values(),
            new_emg=new_emg, new_cop=new_cop, state=self.state, elapsed_s=elapsed,
            duration_s=self.duration_s, recording_done=done, rates=self.rates(),
        )

    def rates(self) -> Dict[str, float]:
        r = {}
        if self.emg is not None:
            r["emg_hz"] = self.emg.rate.rate()
        if self.cop is not None:
            r["cop_hz"] = self.cop.rate.rate()
        if self.pose is not None:
            r["pose_fps"] = self.pose.inference_rate.rate()
            r["camera_fps"] = self.pose.capture_rate.rate()
        return r

    def status_text(self) -> str:
        parts = []
        r = self.rates()
        if self.emg is not None:
            parts.append(f"EMG[{self.emg.source}] {r.get('emg_hz', 0):.0f} Hz")
        if self.cop is not None:
            parts.append(f"CoP {r.get('cop_hz', 0):.0f} Hz {self._cop_kg:.1f} kg")
        if self.pose is not None:
            parts.append(f"Pose {r.get('pose_fps', 0):.1f} fps")
        for name, err in self.errors.items():
            if err:
                parts.append(f"{name.upper()} offline")
        return " | ".join(parts) or "no hardware"

    # ---------- saving ----------
    def snapshot(self) -> RecordingSnapshot:
        """Take on the GUI thread; pass to export() on a background thread."""
        return self.recorder.snapshot()

    def metadata(self) -> dict:
        info = {
            "software_revision": _git_revision(),
            "started": self._started_wall,
            "duration_s": self.duration_s,
            "config": config_to_dict(self.cfg),
            "connect_errors": self.errors,
            "emg_source": getattr(self.emg, "source", None),
        }
        if self.emg is not None:
            info["emg_worker"] = {"dropped": self.emg.dropped_samples, "parse_errors": self.emg.parse_errors}
        if self.cop is not None:
            info["cop_worker"] = {"dropped": self.cop.dropped_samples, "tare": self.cop.tare_info,
                                  "data_interval_ms": self.cop.actual_interval_ms, "warnings": self.cop.warnings,
                                  "incomplete_frames": self.cop._assembler.incomplete_frames}
        if self.pose is not None:
            lat = list(self.pose.latency_ms)
            info["pose_worker"] = {"source": self.pose.source_name, "dropped_frames": self.pose.frames_dropped,
                                   "processed": self.pose.processed, "detections": self.pose.detections,
                                   "latency_ms_p50": float(np.percentile(lat, 50)) if lat else None,
                                   "latency_ms_p95": float(np.percentile(lat, 95)) if lat else None}
        return info

    def export(self, snapshot: RecordingSnapshot, base_name: str = "", out_dir: Optional[str] = None,
               postprocess: bool = True) -> Dict[str, str]:
        base = (base_name or "").strip() or f"session_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out_dir = out_dir or sessions_dir()
        paths = self.recorder.export(out_dir, base, metadata=self.metadata(), snapshot=snapshot)
        if postprocess and len(snapshot.emg) >= 8:
            try:
                from acquisition_systems.postprocess import process_emg_csv
                png = os.path.splitext(paths["emg"])[0] + "_processed.png"
                paths["emg_processed"] = process_emg_csv(paths["emg"], png_path=png, verbose=False)
                paths["emg_figure"] = png
            except Exception as exc:
                print(f"[Session] post-processing skipped: {exc}")
        return paths


# ---------------------------------------------------------------------------
# Headless runner (SSH):  python -m acquisition_systems.session --duration 20
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Headless synchronous acquisition (no GUI).")
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--emg-source", choices=["auto", "bluetooth", "simulated"])
    p.add_argument("--no-emg", action="store_true")
    p.add_argument("--no-cop", action="store_true")
    p.add_argument("--no-pose", action="store_true")
    p.add_argument("--name", default="")
    p.add_argument("--out", default=None)
    p.add_argument("--headless", action="store_true", help="accepted for clarity; this runner never opens a GUI")
    args = p.parse_args(argv)

    session = AcquisitionSession(emg_source=args.emg_source, enable_emg=not args.no_emg,
                                 enable_cop=not args.no_cop, enable_pose=not args.no_pose)
    t_connect = time.perf_counter()
    errors = session.connect()
    print(f"[Session] connected in {time.perf_counter() - t_connect:.1f} s; errors={errors}")
    try:
        time.sleep(1.0)
        session.poll()
        session.start_recording(args.duration)
        next_print = time.perf_counter() + 1.0
        while True:
            live = session.poll()
            if time.perf_counter() >= next_print:
                print(f"[Session] t={live.elapsed_s:5.1f}s  {session.status_text()}")
                next_print += 1.0
            if live.recording_done:
                break
            time.sleep(0.033)
        snap = session.snapshot()
        paths = session.export(snap, args.name, args.out)
        meta = session.metadata()
    finally:
        session.close()

    print("\n=== Summary (paper targets: sEMG ~100 Hz, CoP >= 80 Hz, pose ~2 fps baseline) ===")
    for k, n in (("emg", len(snap.emg)), ("cop", len(snap.cop)), ("pose", len(snap.pose))):
        rate = (n - 1) / args.duration if n > 1 else 0.0
        print(f"  {k:5s}: {n:6d} samples  ~{rate:7.2f} Hz recorded")
    print(f"  emg_source: {meta.get('emg_source')}")
    for k, v in paths.items():
        print(f"  {k:14s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
