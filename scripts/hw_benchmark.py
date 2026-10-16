"""
Console verification and benchmarks for the Raspberry Pi (works over SSH).

  python scripts/hw_benchmark.py cop     [--seconds 10]
  python scripts/hw_benchmark.py camera  [--seconds 10] [--snapshot frame.jpg]
  python scripts/hw_benchmark.py pose    [--seconds 20] [--file person.jpg]
  python scripts/hw_benchmark.py emg     [--seconds 10] [--source simulated|bluetooth|auto]
  python scripts/hw_benchmark.py dsp
  python scripts/hw_benchmark.py render  [--frames 60]
  python scripts/hw_benchmark.py e2e     [--seconds 20] [--emg-source simulated]

Every command prints the real rates (Hz / fps), interval jitter (p50/p95),
dropped samples and, where relevant, the 40 Hz (aliased 60 Hz) attenuation.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acquisition_systems.common.config import config_to_dict, load_config
from acquisition_systems.common.utils import drain


def _intervals(ts):
    if len(ts) < 3:
        return "n/a"
    d = np.diff(ts) * 1000.0
    return f"p50={np.percentile(d, 50):.2f} ms p95={np.percentile(d, 95):.2f} ms max={d.max():.1f} ms"


def _tone_db(raw, filt, fs, freq):
    def power(x):
        x = np.asarray(x) - np.mean(x)
        spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
        f = np.fft.rfftfreq(x.size, 1 / fs)
        k = int(np.argmin(np.abs(f - freq)))
        return spec[max(0, k - 2):k + 3].max() + 1e-12
    return 20 * np.log10(power(filt) / power(raw))


def bench_cop(a):
    from acquisition_systems.workers.cop import CoPWorker
    cfg = load_config()
    w = CoPWorker(cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms,
                  flip_x=cfg.cop_flip_x, flip_y=cfg.cop_flip_y, swap_xy=cfg.cop_swap_xy,
                  bridge_gain=cfg.cop_bridge_gain, min_load_kg=cfg.cop_min_load_kg)
    t = time.perf_counter()
    w.start()
    print(f"[cop] open+calibration+tare: {time.perf_counter() - t:.2f} s; data interval {w.actual_interval_ms} ms")
    print(f"[cop] tare: {w.tare_info}")
    if w.warnings:
        print(f"[cop] warnings: {w.warnings}")
    drain(w.queue)
    samples = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < a.seconds:
        time.sleep(0.033)                 # same cadence as the GUI
        samples += drain(w.queue)
    dt = time.perf_counter() - t0
    w.stop()
    kg = np.array([s.kg for s in samples])
    nan = np.mean([not np.isfinite(s.x) for s in samples]) if samples else 1.0
    print(f"[cop] frames recorded: {len(samples)} in {dt:.1f} s -> {len(samples) / dt:.1f} Hz (paper: >= 80 Hz)")
    print(f"[cop] intervals: {_intervals([s.t for s in samples])}")
    print(f"[cop] dropped={w.dropped_samples} incomplete_frames={w._assembler.incomplete_frames}")
    if kg.size:
        print(f"[cop] total load: mean={kg.mean():.2f} kg std={kg.std():.3f} kg; CoP NaN (unloaded) fraction={nan:.2f}")


def bench_camera(a):
    from acquisition_systems.workers.camera import LatestFrameGrabber, open_frame_source, to_rgb
    cfg = load_config()
    src = open_frame_source(cfg.cam_backend if not a.file else "file", cfg.cam_index, cfg.cam_width,
                            cfg.cam_height, cfg.cam_fps, a.file or cfg.cam_file)
    print(f"[camera] source={type(src).__name__}")
    g = LatestFrameGrabber(src)
    g.start()
    time.sleep(1.0)
    c0, t0 = g.captured, time.perf_counter()
    time.sleep(a.seconds)
    fps = (g.captured - c0) / (time.perf_counter() - t0)
    item = g.wait_newer(0, 1.0)
    if item and a.snapshot:
        import cv2
        rgb = to_rgb(item[2], src.fmt, cfg.cam_width, cfg.cam_height, cfg.cam_rotation, cfg.cam_hflip)
        cv2.imwrite(a.snapshot, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        print(f"[camera] snapshot {rgb.shape[1]}x{rgb.shape[0]} -> {a.snapshot}")
    g.stop()
    print(f"[camera] capture: {fps:.1f} fps (requested {cfg.cam_fps})")


def bench_pose(a):
    from acquisition_systems.workers.pose import PoseWorker
    cfg = load_config()
    conf = config_to_dict(cfg)
    if a.file:
        conf.update(cam_backend="file", cam_file=a.file)
    w = PoseWorker(cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps, config=conf)
    w.start()
    time.sleep(3.0)                       # model warm-up
    drain(w.queue)
    p0, cap0, t0 = w.processed, w._grabber.captured, time.perf_counter()
    samples = []
    while time.perf_counter() - t0 < a.seconds:
        time.sleep(0.033)
        samples += drain(w.queue)
    dt = time.perf_counter() - t0
    proc, cap = w.processed - p0, w._grabber.captured - cap0
    lat = np.array(w.latency_ms)
    w.stop()
    det = [s for s in samples if s.detected]
    ang = np.array([s.angle_deg for s in det if np.isfinite(s.angle_deg)])
    print(f"[pose] source={w.source_name} model_complexity={w.model_complexity}")
    print(f"[pose] camera {cap / dt:.1f} fps -> MediaPipe {proc / dt:.2f} fps (paper baseline ~2 fps); "
          f"stale frames skipped={max(0, cap - proc)}")
    print(f"[pose] samples recorded {len(samples) / dt:.2f}/s, detected {len(det)}/{len(samples)}; "
          f"latency capture->landmarks p50={np.percentile(lat, 50):.0f} ms p95={np.percentile(lat, 95):.0f} ms")
    if ang.size:
        print(f"[pose] pelvic obliquity: mean={ang.mean():.2f} deg std={ang.std():.2f} deg")


def bench_emg(a):
    from acquisition_systems.common.dsp import fft_notch
    from acquisition_systems.workers.emg import EMGWorker
    cfg = load_config()
    w = EMGWorker(cfg.emg_mac, cfg.emg_com_port, cfg.emg_rfcomm_channel, cfg.emg_vmin, cfg.emg_vmax,
                  start_token=cfg.emg_start_token, stop_token=cfg.emg_stop_token,
                  sample_rate_hz=cfg.emg_sample_rate_hz, source=a.source,
                  connect_timeout_s=cfg.emg_connect_timeout_s)
    w.start()
    if not w.wait_ready(cfg.emg_connect_timeout_s + 4):
        print(f"[emg] not connected: {w.error}")
        w.stop()
        return
    samples, arrivals = [], []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < a.seconds:
        time.sleep(0.033)
        got = drain(w.queue)
        if got:
            arrivals.append(time.perf_counter())
        samples += got
    dt = time.perf_counter() - t0
    w.stop()
    v = np.array([s.value for s in samples])
    print(f"[emg] source={w.source}: {len(samples)} samples in {dt:.1f} s -> {len(samples) / dt:.2f} Hz (paper ~100 Hz)")
    print(f"[emg] sample clock {_intervals([s.t for s in samples])}; parse_errors={w.parse_errors} dropped={w.dropped_samples}")
    if v.size > 64:
        f = fft_notch(v, cfg.emg_sample_rate_hz, cfg.emg_powerline_hz, cfg.emg_notch_bandwidth_hz)
        print(f"[emg] 60 Hz interference (alias 40 Hz) after FFT notch: {_tone_db(v, f, cfg.emg_sample_rate_hz, 40):.1f} dB")
        print(f"[emg] first sample {v[0]:.3f} V, max of first 0.5 s {v[:50].max():.3f} V (no t=0 spike)")


def bench_dsp(a):
    from collections import deque
    from scipy import signal
    from acquisition_systems.common.dsp import RealtimeEmgFilter, fft_notch, iir_notch_sos
    from acquisition_systems.workers.emg_sim import EmgSignalModel
    fs = 100.0
    x = np.asarray(EmgSignalModel(fs).generate(int(300 * fs)))
    reps = 50

    def timeit(fn):
        t = time.perf_counter()
        for _ in range(reps):
            out = fn()
        return (time.perf_counter() - t) / reps * 1000, out

    buf = deque(x[-30000:], maxlen=30000)
    sos_old = signal.iirnotch(40.0, 10.0, fs=fs)
    sos_old = signal.tf2sos(*sos_old)
    ms, _ = timeit(lambda: signal.sosfiltfilt(sos_old, np.array(list(buf)[-5000:])))
    print(f"[dsp] previous GUI tick (deque copy + sosfiltfilt 5000 samples): {ms:.3f} ms")
    for secs in (10, 60, 300):
        seg = x[:int(secs * fs)]
        ms, out = timeit(lambda: fft_notch(seg, fs))
        print(f"[dsp] naive full-record FFT notch at {secs:>3d} s: {ms:.3f} ms/tick (grows with recording length)")
    for method in ("fft", "iir"):
        f = RealtimeEmgFilter(fs, 5.0, method)
        f.extend(np.arange(500) / fs, x[:500])
        chunk = x[500:503]
        def tick():
            f.extend(np.arange(3) / fs, chunk)
            return f.window()
        ms, (_, y) = timeit(tick)
        print(f"[dsp] RealtimeEmgFilter[{method}] 5 s window, 3 new samples/tick: {ms:.3f} ms/tick")
    raw = x[:2000]
    print(f"[dsp] 40 Hz attenuation: fft_notch {_tone_db(raw, fft_notch(raw, fs), fs, 40):.1f} dB, "
          f"iir {_tone_db(raw, signal.sosfilt(iir_notch_sos(fs, 60.0), raw), fs, 40):.1f} dB")


def bench_render(a):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure
    rng = np.random.default_rng(0)
    n = a.frames

    def figure():
        fig = Figure(figsize=(11, 7), dpi=100)
        return fig, FigureCanvasAgg(fig), fig.subplots(2, 2).ravel()

    fig, canvas, axes = figure()
    t = time.perf_counter()
    for _ in range(n):
        for ax in axes:
            ax.clear()
        axes[0].plot(rng.random(500)); axes[1].plot([0], [0], "o"); axes[1].set_xlim(-27.94, 27.94)
        axes[2].plot(rng.random(33) * 640, rng.random(33) * 480, "o"); axes[3].plot(rng.random(80)); axes[3].set_ylim(-40, 40)
        canvas.draw()
    naive = (time.perf_counter() - t) / n * 1000

    fig, canvas, axes = figure()
    lines = [axes[0].plot([], [])[0], axes[1].plot([], [], "o")[0], axes[2].plot([], [], "o")[0], axes[3].plot([], [])[0]]
    for ax, lim in zip(axes, ((0, 500, 0, 1), (-27.94, 27.94, -20.32, 20.32), (0, 640, 480, 0), (0, 80, -40, 40))):
        ax.axis(lim)
    t = time.perf_counter()
    for _ in range(n):
        lines[0].set_data(np.arange(500), rng.random(500)); lines[1].set_data([0], [0])
        lines[2].set_data(rng.random(33) * 640, rng.random(33) * 480); lines[3].set_data(np.arange(80), rng.random(80))
        canvas.draw()
    setdata = (time.perf_counter() - t) / n * 1000

    for ln in lines:
        ln.set_animated(True)
    lc = LineCollection([], animated=True); axes[2].add_collection(lc)
    canvas.draw()
    bgs = [canvas.copy_from_bbox(ax.bbox) for ax in axes]
    t = time.perf_counter()
    for _ in range(n):
        lines[0].set_data(np.arange(500), rng.random(500)); lines[1].set_data([0], [0])
        pts = rng.random((33, 2)) * (640, 480)
        lines[2].set_data(pts[:, 0], pts[:, 1]); lc.set_segments(pts[rng.integers(0, 33, (35, 2))])
        lines[3].set_data(np.arange(80), rng.random(80))
        for ax, bg, arts in zip(axes, bgs, ([lines[0]], [lines[1]], [lines[2], lc], [lines[3]])):
            canvas.restore_region(bg)
            for art in arts:
                ax.draw_artist(art)
            canvas.blit(ax.bbox)
    blit = (time.perf_counter() - t) / n * 1000
    print(f"[render] matplotlib ax.clear()+plot+draw : {naive:7.1f} ms/frame ({1000 / naive:5.1f} FPS)")
    print(f"[render] matplotlib set_data + draw      : {setdata:7.1f} ms/frame ({1000 / setdata:5.1f} FPS)")
    print(f"[render] matplotlib blitting (4 axes)    : {blit:7.1f} ms/frame ({1000 / blit:5.1f} FPS)  [Agg only; Tk copy measured in the GUI]")

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
        from PyQt5 import QtWidgets
        import pyqtgraph as pg
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        w = pg.GraphicsLayoutWidget(); w.resize(1100, 700)
        p = [w.addPlot(), w.addPlot()]; w.nextRow(); p += [w.addPlot(), w.addPlot()]
        c = [p[0].plot(), pg.ScatterPlotItem(), pg.ScatterPlotItem(), p[3].plot()]
        p[1].addItem(c[1]); p[2].addItem(c[2]); sk = p[2].plot(connect="pairs")
        w.show(); app.processEvents()
        t = time.perf_counter()
        for _ in range(n):
            c[0].setData(np.arange(500), rng.random(500)); c[1].setData([0], [0])
            pts = rng.random((33, 2)) * (640, 480)
            c[2].setData(pts[:, 0], pts[:, 1]); sk.setData(*pts[rng.integers(0, 33, 70)].T)
            c[3].setData(np.arange(80), rng.random(80))
            w.repaint(); app.processEvents()
        qt = (time.perf_counter() - t) / n * 1000
        print(f"[render] PyQtGraph setData + repaint     : {qt:7.1f} ms/frame ({1000 / qt:5.1f} FPS)")
    except Exception as exc:
        print(f"[render] PyQtGraph not measured: {exc}")


def bench_e2e(a):
    from acquisition_systems.session import main as session_main
    args = ["--duration", str(a.seconds)]
    if a.emg_source:
        args += ["--emg-source", a.emg_source]
    session_main(args)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["cop", "camera", "pose", "emg", "dsp", "render", "e2e"])
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--frames", type=int, default=60)
    p.add_argument("--snapshot")
    p.add_argument("--file", help="image/video replayed instead of the live camera")
    p.add_argument("--source", default="simulated", choices=["auto", "bluetooth", "simulated"])
    p.add_argument("--emg-source", choices=["auto", "bluetooth", "simulated"])
    a = p.parse_args()
    globals()[f"bench_{a.command}"](a)


if __name__ == "__main__":
    main()
