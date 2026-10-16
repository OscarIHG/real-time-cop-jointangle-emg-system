# -*- coding: utf-8 -*-
"""
Installation and hardware diagnostic (Windows and Raspberry Pi / Linux).

    python -m acquisition_systems.doctor            # full check
    python -m acquisition_systems.doctor --quick    # skip opening hardware

Prints one line per check (OK / WARN / FAIL) with a hint for every problem.
Exit status is 1 only when something required to start the application is
missing; absent hardware is a warning because each module can run alone (and
the EMG falls back to the built-in simulator).
"""
import argparse
import importlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from typing import List, Tuple

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
_results: List[Tuple[str, str, str, str]] = []


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        # Windows 10+ consoles understand ANSI once virtual terminal mode is on.
        os.system("")
    return sys.stdout.isatty()


def report(status: str, name: str, detail: str = "", hint: str = "") -> None:
    _results.append((status, name, detail, hint))
    tag = f"{_COLORS[status]}{status:4s}\033[0m" if _supports_color() else f"{status:4s}"
    print(f"  [{tag}] {name}" + (f": {detail}" if detail else ""))
    if hint and status != OK:
        print(f"         -> {hint}")


def section(title: str) -> None:
    print(f"\n{title}")


# ---------------------------------------------------------------------------
def check_python() -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if (v.major, v.minor) == (3, 11):
        report(OK, "Python", detail)
    else:
        report(WARN, "Python", detail, "MediaPipe 0.10.x needs Python 3.11: run setup.sh / setup.ps1")


def check_packages() -> bool:
    required = [("numpy", "numpy"), ("scipy", "scipy"), ("pandas", "pandas"), ("yaml", "PyYAML"),
                ("matplotlib", "matplotlib"), ("cv2", "opencv-python"), ("mediapipe", "mediapipe"),
                ("Phidget22", "Phidget22"), ("serial", "pyserial"), ("PyQt5.QtCore", "PyQt5"),
                ("pyqtgraph", "pyqtgraph"), ("tkinter", "tkinter")]
    all_ok = True
    for module, package in required:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", getattr(mod, "PYQT_VERSION_STR", ""))
            report(OK, package, str(version))
        except Exception as exc:
            all_ok = False
            report(FAIL, package, f"{type(exc).__name__}: {exc}", "re-run the setup script for your platform")
    try:
        import mediapipe as mp
        if not hasattr(mp, "solutions"):
            raise AttributeError("mediapipe.solutions missing")
        report(OK, "MediaPipe Pose API", "mp.solutions.pose available")
    except Exception as exc:
        all_ok = False
        report(FAIL, "MediaPipe Pose API", str(exc), "install mediapipe>=0.10.14,<0.11 (see requirements.txt)")
    return all_ok


def check_config():
    try:
        from acquisition_systems.common.config import load_config
        cfg = load_config()
        report(OK, "config.yaml", f"gui={cfg.gui_backend} emg_source={cfg.emg_source} "
                                  f"emg={cfg.emg_sample_rate_hz:g} Hz cop={1000 // cfg.cop_interval_ms} Hz")
        return cfg
    except Exception as exc:
        report(FAIL, "config.yaml", str(exc), "fix the value reported above")
        return None


def check_force_plate(cfg, quick: bool) -> None:
    try:
        from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput
        from Phidget22.Net import Net  # noqa: F401  (import fails if the native library is missing)
    except Exception as exc:
        hint = ("install the Phidget22 driver (setup.ps1 does it, or phidgets.com/docs/OS_-_Windows)"
                if os.name == "nt" else "run ./setup.sh (installs libphidget22)")
        report(FAIL, "Phidget22 library", str(exc), hint)
        return
    report(OK, "Phidget22 library", "native driver loaded")
    if quick:
        return
    ch = VoltageRatioInput()
    ch.setChannel(0)
    try:
        ch.openWaitForAttachment(3000)
        name = ch.getDeviceName()
        serial = ch.getDeviceSerialNumber()
        report(OK, "PhidgetBridge", f"{name} (serial {serial})")
    except Exception as exc:
        text = str(exc)
        if "access" in text.lower() or "permission" in text.lower():
            hint = "unplug and re-plug the USB cable, then log out/in so the plugdev group applies"
        elif os.name == "nt":
            hint = "connect the 1046_1 by USB; check it appears in the Phidget Control Panel"
        else:
            hint = "connect the 1046_1 by USB (lsusb should list 06c2:003b)"
        report(WARN, "PhidgetBridge", f"not detected ({text.splitlines()[0] if text else 'timeout'})", hint)
    finally:
        try:
            ch.close()
        except Exception:
            pass


def check_camera(cfg, quick: bool) -> None:
    from acquisition_systems.workers.camera import rpicam_binary, rpicam_has_camera
    csi = bool(rpicam_binary()) and rpicam_has_camera()
    if rpicam_binary():
        if csi:
            report(OK, "CSI camera (libcamera)", "detected")
        elif cfg.cam_backend == "rpicam":
            report(WARN, "CSI camera (libcamera)", "none detected but cam_backend is rpicam",
                   "check the ribbon cable and run: rpicam-hello --list-cameras")
        else:
            report(OK, "CSI camera (libcamera)", "none detected; a USB camera will be used")
    if quick:
        return
    from acquisition_systems.workers.camera import open_frame_source
    backend = cfg.cam_backend if cfg.cam_backend != "file" else "auto"
    t0 = time.perf_counter()
    try:
        src = open_frame_source(backend, cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps)
    except Exception as exc:
        report(WARN, "Camera", f"cannot open ({exc})",
               "change cam_index in config.yaml (0, 1, 2...) or check the cable")
        return
    try:
        frames, deadline = 0, time.perf_counter() + 3.0
        shape = None
        while time.perf_counter() < deadline:
            ok, frame = src.read()
            if ok:
                frames += 1
                shape = getattr(frame, "shape", None)
        if frames:
            size = f"{shape[1]}x{shape[0]}" if shape is not None and len(shape) >= 2 else f"{cfg.cam_width}x{cfg.cam_height}"
            report(OK, "Camera", f"{type(src).__name__} {size}, {frames} frames in "
                                 f"{time.perf_counter() - t0:.1f} s")
        else:
            report(WARN, "Camera", "opened but delivered no frames", "close other apps using the camera")
    finally:
        src.close()


def check_emg(cfg) -> None:
    if cfg.emg_source == "simulated":
        report(OK, "EMG source", "simulated (no ESP32 needed)")
        return
    fallback = " - the built-in simulator will be used" if cfg.emg_source == "auto" else ""
    level = WARN
    if os.name == "nt":
        try:
            from serial.tools import list_ports
            ports = {p.device: p for p in list_ports.comports()}
        except Exception:
            ports = {}
        port = ports.get(cfg.emg_com_port)
        bt_ports = [d for d, p in ports.items() if "bluetooth" in (p.description or "").lower()
                    or "BTHENUM" in (p.hwid or "").upper()]
        if port is not None:
            report(OK, "ESP32 COM port", f"{cfg.emg_com_port} present ({port.description})")
        else:
            report(level, "ESP32 COM port", f"{cfg.emg_com_port} not found{fallback}",
                   f"pair the ESP32, then set emg_com_port to its OUTGOING port. Bluetooth ports now: "
                   f"{', '.join(bt_ports) or 'none'}")
        return
    if not hasattr(socket, "AF_BLUETOOTH") and not os.path.exists("/usr/bin/python3"):
        report(level, "Bluetooth RFCOMM", f"not available{fallback}", "install python3 from apt (system Python)")
        return
    if not shutil.which("bluetoothctl"):
        report(level, "Bluetooth", f"bluetoothctl not found{fallback}", "run ./setup.sh (installs bluez)")
        return
    try:
        out = subprocess.run(["bluetoothctl", "info", cfg.emg_mac], capture_output=True, text=True, timeout=8).stdout
    except Exception as exc:
        report(level, "ESP32 pairing", f"cannot query bluetoothctl ({exc}){fallback}")
        return
    paired = "Paired: yes" in out
    name = next((line.split(":", 1)[1].strip() for line in out.splitlines() if line.strip().startswith("Name:")), "")
    if paired:
        report(OK, "ESP32 pairing", f"{cfg.emg_mac} paired ({name or 'unnamed'})")
    else:
        report(level, "ESP32 pairing", f"{cfg.emg_mac} not paired{fallback}",
               "bluetoothctl -> scan on -> pair <MAC> -> trust <MAC>, then set emg_mac in config.yaml")


def check_display(cfg) -> None:
    if os.name == "nt" or sys.platform == "darwin":
        report(OK, "Display", "desktop session")
        return
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        report(OK, "Display", f"DISPLAY={os.environ.get('DISPLAY', '')} WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}")
    else:
        report(WARN, "Display", "no graphical session in this terminal (e.g. SSH)",
               "run on the Pi's desktop, or: export DISPLAY=:0 XAUTHORITY=~/.Xauthority  "
               "(headless: python -m acquisition_systems.session)")


def check_groups() -> None:
    if os.name == "nt" or not hasattr(os, "getgroups"):
        return
    import grp
    names = set()
    for gid in os.getgroups():
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            pass
    missing = [g for g in ("plugdev", "dialout", "video") if g not in names]
    if missing:
        report(WARN, "User groups", f"missing {', '.join(missing)} in this session",
               "log out and back in (or reboot) after running setup.sh")
    else:
        report(OK, "User groups", "plugdev, dialout, video")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check the installation and connected hardware.")
    p.add_argument("--quick", action="store_true", help="do not open the force plate or the camera")
    args = p.parse_args(argv)

    print(f"Real-Time CoP-JointAngle-EMG diagnostic - {platform.system()} {platform.release()} ({platform.machine()})")
    section("Software")
    check_python()
    packages_ok = check_packages()
    cfg = check_config()
    if cfg is None or not packages_ok:
        print("\nResult: FAIL - fix the items above, then run this diagnostic again.")
        return 1

    section("Hardware")
    check_groups()
    check_force_plate(cfg, args.quick)
    check_camera(cfg, args.quick)
    check_emg(cfg)
    check_display(cfg)

    fails = sum(1 for r in _results if r[0] == FAIL)
    warns = sum(1 for r in _results if r[0] == WARN)
    if fails:
        print(f"\nResult: FAIL ({fails} error(s), {warns} warning(s))")
        return 1
    if warns:
        print(f"\nResult: READY with {warns} warning(s) - review them above.")
    else:
        print("\nResult: READY - all checks passed.")
    print("Start the application with:  python -m acquisition_systems.app_gui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
