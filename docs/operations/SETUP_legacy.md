# Setup

## Minimum Steps

1. Install 64-bit Python 3.x.
2. Create and activate a virtual environment.
3. Install the requirements from `stcs_v1/requirements.txt`.
4. Run the GUI from the project root.

## Commands

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r stcs_v1\requirements.txt
python stcs_v1\src\main.py
```

## Hardware / Service Requirements

- GPS serial receiver for live GPS data
- Telescope/mount Arduino serial devices for full control
- Optional LightField camera installation for the science camera
- Optional local Alpaca and telemetry services started by the app

## Troubleshooting

- If the app fails with `ModuleNotFoundError: No module named 'PyQt6'`, install the requirements inside the active virtual environment.
- If the science camera does not connect, check `LIGHTFIELD_ROOT` and the Princeton Instruments LightField installation.
- If serial devices are missing, the app may still open, but hardware-driven features will stay offline.
