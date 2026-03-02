# Astro Joystick Telescope Controller

Tkinter desktop app that lets you steer an ASCOM-compatible telescope mount with a joystick on Windows. You can pick a joystick, map buttons to change slew speed, connect to a mount, monitor live RA/Dec and tracking, choose a target (manual or popular objects), see distance to target, view a pointing crosshair, and toggle tracking.

## Features
- Modern dark Tkinter UI with live mount readouts
- Joystick selection and on-the-fly button mapping for speed up/down
- Mount picker (ASCOM drivers) with tracking toggle
- Target entry plus a curated list of popular objects
- Distance readout in degrees/arc-min/arc-sec with green indicator inside 1 arc-minute
- Crosshair and direction hints to reach the target
- Optional screenshot mode for documentation (`--screenshot path`)

## Requirements
- Windows with ASCOM platform installed for real mount control
- Python 3.9+
- Optional/extra packages (listed in `requirements.txt`):
  - `pygame` for joystick input
  - `comtypes` / `pywin32` for ASCOM COM access
  - `Pillow` for screenshot support

## Usage

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\\Scripts\\activate on Windows
pip install -r requirements.txt
python main.py
```

Steps:
1. Refresh and select your joystick, then click **Assign Increase/Decrease** and press the desired buttons.
2. Refresh and choose your mount driver, then click **Connect**. Toggle tracking as needed.
3. Enter a target RA/Dec or pick a popular target and click **Set Target**.
4. Use the joystick axes to slew; watch RA/Dec, distance, and crosshair guidance.

To capture a UI screenshot (requires Pillow):

```bash
python main.py --screenshot ui.png
```

## Project layout

- `main.py` — small entry point
- `astro_joystick/` — package modules:
  - `ui.py` — Tkinter UI
  - `joystick.py` — pygame integration and button mapping
  - `telescope.py` — ASCOM/mount handling with simulator fallback
  - `utils.py` — coordinate helpers
  - `constants.py` — popular targets and slew speeds
