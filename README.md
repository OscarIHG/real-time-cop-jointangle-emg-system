# Real-Time CoP, Joint Angle, and EMG System

## System Overview
This project collects three streams of body data at once:
- abdominal muscle activity (EMG)
- center of pressure from a force plate (CoP)
- hip tilt based on landmarks from a camera

It can display live graphs in a window or run silently for recordings. Each stream is optional, so the program keeps working even if a device is missing.

![System overview diagram](docs/system-overview.png)

## Installation
1. Clone this repository.
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Adjust hardware settings in `config.yaml` if needed.

## Running the GUI
Start the graphical interface with:
```bash
python -m acquisition_systems.app_gui
```
It shows live plots and provides buttons to start, save, or quit a session.

![GUI screenshot](docs/gui-screenshot.png)

## Headless Recording
The recorder can also run without the window:
```bash
python -m examples.headless_record
```
### Non-interactive flags
Use these flags to skip prompts:
- `--duration SECONDS` – how long to record
- `--name FILE_BASENAME` – base name for the output file
- `--append-suffix` – add a time stamp to the file name
- `--reference {auto, emg, cop, pose, angle}` – choose which stream sets the timeline
- `--save` / `--no-save` – save or discard automatically
- `--no-emg`, `--no-cop`, `--no-pose` – skip individual devices
- `--no-prompt` – disable questions even if other flags are missing

Example:
```bash
python -m examples.headless_record --duration 12 --name test --append-suffix --reference cop --save
```

## Data Output
Recordings are written as CSV files. A merged file lines up all streams and keeps the last known value when a sample is missing.

## Pelvic Tilt Formula
Here the pelvic angle is derived from two hip points detected by the camera.

$$\theta = \mathrm{arctan2}(y_R - y_L, x_R - x_L)$$

*(Replace this with your formatted formula if needed.)*

## Notes and Diagrams
Include diagrams or photos showing sensor placement and coordinate directions here.

![Hardware layout](docs/hardware-layout.png)

## License
Add licensing information here.

