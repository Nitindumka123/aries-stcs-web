# PROJECT CONTEXT

## Project Purpose

This is the ARIES STCS (Telescope Control System) for the 104 cm Sampurnanand Telescope at ARIES, Nainital. The existing STCS-V1 system is a working PyQt6 desktop GUI that controls the telescope, dome, GPS, weather, camera, and associated observatory hardware. This project modernizes the existing working system by adding a web-based interface and authentication, while preserving all existing functionality.

The modernization is additive and incremental — the existing PyQt6 desktop application must continue to work unchanged.

## ARIES/104 cm Telescope Context

- **Telescope**: 104 cm Sampurnanand Telescope
- **Location**: ARIES, Nainital (Latitude: 29.3586°, Longitude: 79.45799°, Height: 1951 m)
- **Hardware**: DUO Mega 2560 Arduino for relay control, incremental encoders for RA/DEC, 100 PPR dome encoder, GPS receiver (LOCOSYS), weather sensors via UDP, optional LightField camera, ASCOM Alpaca server
- **Operating Mode**: CONFIGURABLE via TELESCOPE_MODE env var — "REAL" (read from encoder Arduinos) or "SIMULATION" (physics engine for testing/development)

## Current System Status

**VERIFIED WORKING FUNCTIONALITY** (from source code inspection):

- **PyQt6 Desktop GUI** (main_window.py): Full telescope control dashboard with telemetry, command deck, environment panel
- **MotionState** (motion_state.py): Thread-safe motion state manager with safety interlocks, relay payload builder (7-byte :UXXXXXXX# protocol for DUO Mega 2560)
- **SlewEngine** (slew_engine.py): Smart slew with waypoint routing, axis priority, sequential movement, speed transition protection, reversal protection with cooldown
- **Safety System** (safety.py): Altitude interlock predictive guard blocks motion that would push telescope below configured altitude floor; includes combined-motion blocking
- **TelemetryWorker** (telemetry_worker.py): Polls hardware via MountCoordinator at 10Hz, sends telemetry dict to GUI; supports serial connection to Arduino R4s for RA/DEC/Dome encoders
- **GPSWorker** (gps_worker.py): Polls LOCOSYS GPS at 115200 baud auto-discovery; emits NMEA data (GGA/RMC/GSV); updates AstrometryEngine location
- **WeatherWorker** (weather_worker.py): Listens on UDP port 12344 for weather broadcasts (temp, humidity, dewpoint); safety thresholds configured but alerts not actively enforced
- **AlpacaServerThread** (alpaca_server.py): ASCOM Alpaca REST HTTP server on port 11111 for Cartes du Ciel; provides telescope coordinate, state, and slew endpoints; includes coordinate cache thread (10Hz RA/DEC/LST, 2Hz Alt/Az)
- **TelemetryServerThread** (telemetry_server.py): FastAPI WebSocket server on port 11112; bidirectional mobile remote control with 10Hz telemetry broadcast, command validation, dead man's switch emergency stop on client disconnect
- **SimulationEngine** (simulation_engine.py): Physics engine thread that simulates telescope position at 10Hz when TELESCOPE_MODE=SIMULATION; applies tracking rate, manual jog, slew speeds; emits telemetry_updated signals for UI
- **MountCoordinator** (mount_coordinator.py): Manages RA/DEC/Dome drivers, persistent offsets (dec_offset_counts, dome_offset_counts), DEC index homing, sync_coordinates, set_dec_home; saves state to config/state.json every 60s
- **LegacyDecoder** (legacy_decoder.py): Converts raw encoder counts to astronomical coordinates per aries1m.c logic; HRA→RA via LST; mounting biases (-2100" HRA, +115800" DEC default); minor bias adjustment runtime; sync_coordination (:CM# command)
- **AstrometryEngine** (astrometry.py): LST, HRA, AZ/EL, AirMass calculations via Astropy; GPS-overridable location; cached LST (200ms TTL), cached AltAz (1s TTL); IERS auto_download disabled, max_age unlimited to prevent SSL errors
- **Dome Control**: Dome sync worker, manual CW/CCW/OFF control, auto-track sync, geometry constants (radius 5.31m, optical axis 1.58m, offsets)
- **Offset Calibration**: RA/DEC/Dome offset persistence in config/state.json; SET RA/DEC/DOME offsets via UI; minor biases accumulate across sessions
- **Relay Protocol**: :U<c_rah><c_ral><c_dech><c_decl><c_dome><c_acc><c_#> — 7 bytes, each nibble OR'd with 0x30 for ASCII encoding; sent at 10Hz to DUO Mega 2560
- **Emergency Stop**: Cuts all RA/DEC motion, aborted slew, resets state; triggered from UI (motion_panel.stop_requested), WebSocket (/stop command), and dead man's switch

**EXTERNAL CONFIGURATION** (from config files):

- config/settings.json: Connection serial numbers (RA: 3002170F3631393265D733334B572F3E, DEC: 360411295831363889B833334B57303D, Dome: 320F243558313733F09C33334B573026), site lat/lon/elec, park position, guider settings
- config/state.json: Persisted state — dec_offset: 0, dome_offset: 0.0, hra_encoder_zero_bias_arcsec: -19738.6, minor_hra_adj: 0.0, minor_dec_adj: 0.0, dec_home_deg: 29.908305555555554 (+29:37:59.9)
- config/limits.json: Motion limits (min_alt: 45°, max_alt: 89°, min_dec: -50°, max_dec: 70°), environment limits, camera limits
- config/slip_calibration.json: Slip/deadband coefficients per speed tier for RA/DEC; used by SlewEngine _calc_axis_speed_dir and safety checks
- .env: TELESCOPE_MODE=REAL, ALPACA_HOST=0.0.0.0, ALPACA_PORT=11111, SLEW_SPEED_TRANSITION_DELAY_SEC=3, DOME geometry constants

**PROJECT ROOT**: C:\Users\dumka\OneDrive\Desktop\GUI

**DIRECTORY STRUCTURE**:
- .venv/ — Python virtual environment
- data/ — Observation/data storage
- stcs_v1/ — Original PyQt6 desktop application source
  - src/ — Python package
    - main.py — Entry point, loads .env, creates QApplication, shows MainWindow
    - ui/ — PyQt6 UI components (main_window.py, styles.py, components/, windows/, tabs/)
    - core/ — Core logic (motion_state.py, simulation_engine.py, slew_engine.py, safety.py, astrometry.py, legacy_decoder.py)
    - drivers/ — Hardware drivers (mount/, gps/, camera/)
    - workers/ — Background threads/servers (telemetry_worker.py, weather_worker.py, gps_worker.py, alpaca_server.py, telemetry_server.py, camera_worker.py, guider_worker.py, indi_telescope_driver.py, udp_broadcaster.py)
    - config/ — (handled separately)
  - config/ — JSON settings (settings.json, state.json, limits.json, slip_calibration.json)
  - requirements.txt — PyQt6, pyserial, pywin32, numpy, astropy, opencv-python, pypylon, pytest, pythonnet, python-dotenv, requests, pynmea2, fastapi, websockets, uvicorn
  - tests/ — Unit tests, diagnostics, verify_motion.py, test_alpaca_client.py, UI tests
  - data/ — Observation data
  - __MACOSX/ — macOS metadata

## Modernization Objective

Add a modern, professional web application interface that provides access to the same observatory functionality as the existing STCS V1 desktop GUI, through appropriate gateways and safety boundaries. The web application must:

- NOT break or modify existing telescope-control logic
- NOT directly control Arduino, serial hardware, telescope motors, or industrial relays
- Use the existing STCS Core and drivers through controlled backend APIs
- Preserve all existing safety mechanisms
- Operate within the same observatory network environment

## Admin Requirements

- Use telescope functionality
- View telescope status
- Use dome functionality
- View GPS/time information
- View weather/climate information
- Use camera/observation functionality when implemented
- View system information
- View logs where authorized
- Perform observations
- View Admin's own observation history
- View individual Scientist observation histories
- Download permitted observation/research data
- Download PDF data
- Download Excel data
- Download CSV data

## Scientist Requirements

- Use telescope functionality
- View telescope status
- Use observatory functionality
- Use dome functionality where permitted
- View GPS/time information
- View climate/weather information
- Perform observations
- Use camera/observation functionality where implemented
- View their own observation history
- Download their own research/observation data
- Download their own PDF
- Download their own Excel
- Download their own CSV

**Critical**: Scientist A MUST NOT view Scientist B's private observation history, download Scientist B's data, or access research files. This restriction MUST be enforced by the backend/database. Frontend hiding is NOT security.

## Observation Privacy Model

- Each observation record has clear ownership (User → Observation → Data/files/metadata)
- **ADMIN**: Can access permitted observations belonging to all users
- **SCIENTIST**: Can access only observations belonging to that Scientist
- Backend/API must enforce this — never rely only on frontend filtering
- Future observation records must have clear ownership association

## Database Direction

PostgreSQL will be used for the future application/database layer. A PostgreSQL password has been supplied for local development.

**Critical**: Never hard-code database credentials into Python/source files. Use environment variables. Use .env for local development. Use .env.example containing placeholders only. Ensure .env is not committed to Git.

## Climate/Environment Information

The future dashboard should include useful observatory information where actual sources exist:

- Temperature (from weather UDP broadcasts)
- Humidity (from weather UDP broadcasts)
- Wind speed (if available)
- Rain (if available)
- Atmospheric pressure (if available)
- Cloud/sky conditions (if available)
- GPS status
- LST (Local Sidereal Time)
- Telescope position (RA/DEC)
- Telescope state (tracking, slewing, parked)
- Tracking state
- Slew state
- Dome state
- Camera state
- Hardware connection state
- Safety state
- Other useful observatory numbers

**IMPORTANT**: Never fabricate real telemetry. If hardware or sensor is not connected, show: Disconnected / Unavailable / Not connected. Simulation data acceptable only in simulation mode.

## Critical Constraints

1. **NEVER break existing working telescope/hardware communication** (RULE 1)
2. **NEVER rewrite working telescope-control logic without necessity** (RULE 2)
3. **NEVER bypass existing safety mechanisms** (RULE 3)
4. **NEVER allow browser/frontend to directly control physical telescope hardware** (RULE 4)
5. **Backend is authoritative** (RULE 5)
6. **Frontend hiding is not security** (RULE 6)
7. **NEVER fabricate real telemetry** (RULE 7)
8. **NEVER expose secrets** (RULE 8)
9. **NEVER hard-code passwords** (RULE 9)
10. **NEVER destroy existing database data without explicit approval** (RULE 10)
11. **NEVER perform destructive database migrations without approval** (RULE 11)
12. **Test every phase before moving forward** (RULE 12)
13. **Keep implemented/planned/future/unverified clearly separated** (RULE 13)
14. **Inspect actual source code before assuming functionality exists** (RULE 14)
15. **Make small, reversible changes** (RULE 15)
16. **Preserve the existing STCS desktop application** (RULE 16)
17. **New functionality must coexist with the existing STCS system** (RULE 17)
18. **Use useful comments to explain WHY important architectural decisions exist** (RULE 18)
19. **Never make a major architectural change simply because a newer framework is popular** (RULE 19)
20. **If a change could affect physical hardware behavior, STOP and report the risk before implementing it** (RULE 20)

## Integration Boundary

The modernization follows this exact architecture:

```
Scientist/Admin Laptop
        ↓
Modern Web Application Interface (NEW)
        ↓
Authentication & Authorization (NEW — backend enforced)
        ↓
Existing STCS Core (PRESERVE UNCHANGED)
        ↓
Existing Drivers (PRESERVE UNCHANGED)
        ↓
Existing Arduino/Serial Communication (PRESERVE UNCHANGED)
        ↓
Existing Relay System (PRESERVE UNCHANGED)
        ↓
Physical Telescope
```

The browser/frontend must NEVER directly control:
- Arduino
- Serial hardware
- Telescope motors
- Industrial relays
- Physical telescope hardware

The backend will eventually act as the controlled gateway. The existing STCS logic and safety mechanisms remain authoritative.

## Development Philosophy

- **Preserve** the existing working system above all else
- **Additive** changes only — never destructive to existing functionality
- **Incremental** progression through defined phases
- **Source code is authoritative** — never assume documentation is correct
- **Safety first** — all new integration must respect existing safety interlocks
- **Clear separation** of implemented, planned, and future work
- **Backend enforcement** of all security, privacy, and safety rules
- **Useful comments** that explain WHY architectural decisions exist