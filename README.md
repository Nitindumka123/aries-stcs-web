# STCS V1 GUI

Desktop GUI for the ARIES STCS telescope control system.

## Purpose

This project launches a PyQt6 control dashboard for telescope, camera, GPS, weather, telemetry, and Alpaca services.

## Required Python

- 64-bit Python 3.x
- The repository does not pin an exact minor version

## Required Packages

Install from `stcs_v1/requirements.txt`:

- PyQt6
- pyserial
- pywin32
- numpy
- astropy
- opencv-python
- pypylon
- pytest
- pythonnet
- python-dotenv
- requests
- pynmea2
- fastapi
- websockets
- uvicorn

## Environment Setup

1. Create a virtual environment.
2. Activate it.
3. Install the requirements.

Example on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r stcs_v1\requirements.txt
```

## Run Command

```powershell
python stcs_v1\src\main.py
```

## Required Configuration

- Optional `.env` file is loaded at startup.
- `STCS_BUNDLE_ROOT` and `STCS_EXTERNAL_ROOT` are set by `src/main.py`.
- Common runtime variables found in the code:
  - `TELESCOPE_MODE`
  - `LIGHTFIELD_ROOT`
  - `ALPACA_HOST`
  - `ALPACA_PORT`
  - `TELEMETRY_WS_HOST`
  - `TELEMETRY_WS_PORT`
  - `INDI_HOST`
  - `INDI_PORT`
  - `DOME_MAX_SPEED_DPS`
  - `DOME_RAMP_TIME_S`
  - `DOME_COAST_DEG`
  - `DOME_SYNC_TOLERANCE_DEG`
  - `SLEW_SPEED_TRANSITION_DELAY_SEC`

## External Hardware / Services

- PyQt6 GUI runtime
- GPS serial receiver
- Telescope/mount Arduino serial devices
- Optional Princeton Instruments LightField camera stack
- Optional local Alpaca and telemetry servers started by the app
- Weather and mount hardware are expected for full operation

## Known Limitations

- The app did not start in this environment because `PyQt6` is not installed.
- Camera support depends on LightField and `pythonnet`; without that hardware/software it falls back to mock mode.
- The code uses serial auto-discovery, so real devices may be needed for full functionality.

## Basic Folder Structure

- `stcs_v1/src/main.py` starts the GUI.
- `stcs_v1/src/ui/` contains the main window and widgets.
- `stcs_v1/src/core/` contains telescope and safety logic.
- `stcs_v1/src/workers/` contains background threads and servers.
- `stcs_v1/src/drivers/` contains device drivers.
- `stcs_v1/config/` contains runtime JSON settings.
- `stcs_v1/tests/` contains diagnostics and checks.
