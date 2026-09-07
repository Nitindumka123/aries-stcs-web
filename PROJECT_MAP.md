# Project Map

```text
GUI/
├── stcs_v1/
│   ├── src/
│   │   ├── main.py                     # Starts the PyQt6 GUI application
│   │   ├── ui/main_window.py           # Main application window and dashboard
│   │   ├── ui/styles.py                # Application theme and stylesheet values
│   │   ├── ui/components/              # Reusable UI panels and sections
│   │   ├── ui/windows/                 # Secondary popup windows
│   │   ├── ui/widgets/                 # Custom widgets used by the GUI
│   │   ├── core/                       # Telescope, safety, and motion logic
│   │   ├── drivers/                    # Hardware drivers for camera, mount, GPS
│   │   └── workers/                    # Background threads and local servers
│   ├── config/
│   │   ├── settings.json               # Device serial numbers and site settings
│   │   ├── state.json                  # Persisted runtime state
│   │   └── limits.json                 # Safety and operating limits
│   ├── requirements.txt                # Python dependencies
│   ├── build_exe.ps1                   # PyInstaller build helper
│   └── src/dist/STCS_V1.exe           # Packaged executable artifact
├── README.md                           # Quick project overview and run instructions
└── SETUP.md                            # Minimal setup and troubleshooting guide
```

## Important Files

- `stcs_v1/src/main.py` -> Launches the GUI and loads `.env`.
- `stcs_v1/src/ui/main_window.py` -> Builds the main dashboard and starts workers.
- `stcs_v1/src/ui/styles.py` -> Defines the app theme.
- `stcs_v1/src/workers/*.py` -> Starts telemetry, GPS, weather, Alpaca, and websocket services.
- `stcs_v1/src/drivers/*.py` -> Talks to camera, mount, and GPS hardware.
- `stcs_v1/config/settings.json` -> Stores serial numbers, camera path, and site settings.
- `stcs_v1/config/state.json` -> Stores persisted offsets and runtime state.
- `stcs_v1/config/limits.json` -> Stores safety thresholds and limits.
- `stcs_v1/requirements.txt` -> Lists packages needed to run the GUI.
- `stcs_v1/build_exe.ps1` -> Builds the standalone Windows executable.
