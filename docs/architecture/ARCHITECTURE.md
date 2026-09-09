# ARCHITECTURE

## Existing Architecture (Discovered from Source Code)

### Overall System Architecture

The existing STCS V1 system is a **PyQt6 desktop application** that runs Scientist/Admin laptop-side and communicates with telescope hardware through a layered architecture of background workers, drivers, and serial communication.

```
┌─────────────────────────────────────────────────────────────────┐
│  Scientist/Admin Laptop                                            │
│                                                                    │
│  ┌─────────────────┐  PyQt6 GUI  ┌────────────────────────────┐ │
│  │  MainWindow     │◄───────────▶│  QApplication + Styles   │ │
│  │  (src/ui/main.py)│         │  (colors, layout, widgets)│ │
│  └─────────────────┘            └────────────────────────────┘ │
│           │                                                       │
│           ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Central State & Control Logic                              │ │
│  │  ┌─────────────────┐  ┌────────────────────────────┐    │ │
│  │  │ MotionState     │  │  SlewEngine              │    │ │
│  │  │ (thread-safe)   │  │  (smart slew, waypoint)  │    │ │
│  │  └─────────────────┘  └────────────────────────────┘    │ │
│  │           │                       │                     │ │
│  └───────────▼───────────────────────▼───────────────────────┘ │
│  │  ┌─────────────────────────────────────────────────────┐   │ │
│  │  │  Background Workers & Servers                       │   │ │
│  │  │  ├── TelemetryWorker    (serial polling, 10Hz)    │   │ │
│  │  │  ├── WeatherWorker      (UDP listener, 12344)     │   │ │
│  │  │  ├── GPSWorker          (serial GPS, auto-discover)│   │ │
│  │  │  ├── AlpacaServerThread (HTTP on 11111, Alpaca API)│ │ │
│  │  │  ├── TelemetryServerThread (WS on 11112, mobile control)││ │
│  │  │  ├── CameraWorker       (LightField camera)       │   │ │
│  │  │  ├── GuiderWorker       (auto guiding)            │   │ │
│  │  │  └── UDPBroadcaster     ( UDP telemetry broadcast) │   │ │
│  │  └─────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
│           │                                                       │
│           ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Device Drivers                                           │ │
│  │  ┌─────────────────┐  ┌────────────────────────────┐    │ │
│  │  │ MountCoordinator│  │  ControlSerial (DUO Mega 2560)│ │ │
│  │  │ (RA/DEC/Dome)   │  │  (7-byte :UXXXXXXX# protocol)│ │ │
│  │  └─────────────────┘  └────────────────────────────┘    │ │
│  │           │                       │                     │ │
│  │           ▼                       ▼                     │ │
│  │   ┌─────────────────┐  ┌────────────────────────────┐    │ │
│  │   │ SmartSerial     │  │  Arduino R4s (RA, DEC, Dome) │ │ │
│  │   │ Driver          │  │  (incremental encoders, relays)│ │ │
│  │   └─────────────────┘  └────────────────────────────┘    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│           │                                                       │
│           ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Physical Telescope Hardware                              │ │
│  │  ├─ Encoder Arduinos (RA, DEC)                            │ │
│  │  ├─ DUO Mega 2560 (relay controller)                      │ │
│  │  ├─ Dome Controller Arduino                               │ │
│  │  ├─ GPS Receiver (LOCOSYS)                                │ │
│  │  ├─ Weather Sensors (UDP)                                 │ │
│  │  ├─ Telescope Mount & Motors                              │ │
│  │  └─ Optional LightField Camera Stack                      │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Core State Flow

1. **MotionState** (`src/core/motion_state.py`) — Thread-safe central state manager
   - Holds all telescope motion state: RA/DEC speed/direction, dome state, tracking, simulation position
   - Enforces safety interlocks (no opposing directions, mutual exclusion)
   - Builds 7-byte relay payload via `build_relay_payload()`
   - Cooldown management after motion/events
   - All mutations go through setter methods with `_lock` (threading.Lock)

2. **SlewEngine** (`src/core/slew_engine.py`) — Smart slew with waypoint routing
   - Manages automated slew-to-target with obstacle avoidance
   - Determines axis priority (RA-first vs DEC-first) for altitude safety
   - Speed selection based on pointing error thresholds with early cutoff
   - Reversal protection with dead-band hysteresis and cooldown timers
   - Speed transition delay protection (gear protection)
   - Sequential axis movement (FIRST_AXIS → SECOND_AXIS → COMPLETE)
   - Fixed HA targeting for park operations

3. **Safety** (`src/core/safety.py`) — Altitude interlock predictive guard
   - Predicts if motion would push telescope below minimum altitude floor
   - Blocks motion that would cross floor; allows recovery motion
   - Combined-motion blocking (multiple active components)
   - Rate-based projection with lookahead

4. **AstrometryEngine** (`src/core/astrometry.py`) — Astronomical calculations
   - LST, HRA, AZ/EL, AirMass via Astropy
   - GPS-overridable EarthLocation
   - Cached LST (200ms TTL) and AltAz (1s TTL) for 10Hz loop performance
   - IERS auto_download disabled, max_age unlimited (avoid SSL errors)

5. **LegacyDecoder** (`src/core/legacy_decoder.py`) — Encoder count → coordinate conversion
   - HRA counts → HA hours (26-bit A90 absolute encoder, constant 1.287460327)
   - DEC counts → degrees (1000 PPR incremental, 0.9 arcsec/count)
   - Mounting biases (-2100" HRA, +115800" DEC default)
   - Minor runtime biases (minor_hra_adj, minor_dec_adj)
   - Solar sync (:CM# command) — applies sky catalog corrections
   - Counts-to-dome azimuth (100 PPR, 0.010578590109018248 deg/count)

### Worker Thread Architecture

All heavy-down operations run in background QThread subclasses to keep the PyQt6 UI responsive:

- **TelemetryWorker** (`src/workers/telemetry_worker.py`): Polls MountCoordinator at 100ms intervals; reads encoder data from Arduino R4s; emits telemetry_updated signal with full telescope state dict; handles connection status and logging

- **WeatherWorker** (`src/workers/weather_worker.py`): UDP listener on port 12344; receives temp/humidity/dewpoint broadcasts; emits weather_updated signal; safety threshold (humidity > 70%) configured but alerts not actively enforced

- **GPSWorker** (`src/workers/gps_worker.py`): Polls LOCOSYS GPS at 115200 baud auto-discovery; parses NMEA GGA/RMC/GSV sentences; emits gps_data_updated signal; includes event logging for fix acquired/lost/timeout; updates AstrometryEngine location dynamically

- **AlpacaServerThread** (`src/workers/alpaca_server.py`): ASCOM Alpaca HTTP server on port 11111; ThreadingHTTPServer with AlpacaRequestHandler; provides REST API for Cartes du Ciel; includes AlpacaCacheThread (10Hz RA/DEC/LST, 2Hz Alt/Az); UDP discovery on port 32227

- **TelemetryServerThread** (`src/workers/telemetry_server.py`): FastAPI WebSocket server on port 11112; bidirectional mobile remote control; 10Hz telemetry broadcast; validated inbound commands; dead man's switch (emergency stop if client disconnects mid-motion); heartbeat monitoring with 2.0s timeout

- **SimulationEngine** (`src/core/simulation_engine.py`): QThread that simulates telescope position at 10Hz when TELESCOPE_MODE=SIMULATION; applies tracking rate (0.004178074°/sec = true sidereal), manual jog, slew speeds; emits telemetry_updated dict for UI consumption

- **CameraWorker** (`src/workers/camera_worker.py`): Background thread for science camera; Princeton Instruments LightField automation; mock mode when LightField not available (64-bit check, DLL path); comprehensive error handling and stabilization

### Driver Layer

- **MountCoordinator** (`src/drivers/mount/mount_coordinator.py`): Manages RA/DEC/Dome drivers; persistent offset storage (config/state.json); DEC index homing; sync_coordinates; set_dec_home; coordinate conversion; auto-save every 60s; connects to Arduino R4s via serial numbers from config/settings.json

- **ControlSerial** (`src/drivers/mount/control_serial.py`): DUO Mega 2560 relay controller; 7-byte :UXXXXXXX# protocol; each nibble OR'd with 0x30 for ASCII encoding; sent at 10Hz; drain-echo-before-write pattern; no flush() to avoid USB write timeout

- **SmartSerial** (`src/drivers/mount/smart_serial.py`): (Read file list indicates existence) Serial driver with connect/disconnect; used by MountCoordinator for RA/DEC/Dome Arduinos

- **GPSDriver** (`src/drivers/gps/gps_driver.py`): LOCOSYS GPS driver; auto-discovery via NMEA sniffing on available COM ports at 115200 baud; reads and parses NMEA GGA/RMC/GSV; aggregates data into current_data dict

- **ScienceCameraDriver** (`src/drivers/camera/science_driver.py`): Princeton Instruments LightField CCD driver; pythonnet/clr for IPC; mock mode when LightField absent; comprehensive readout mode, gain, temperature, ROI, binning, file save settings

### Configuration & State Persistence

- **config/settings.json**: Connection serial numbers (RA: 3002170F3631393265D733334B572F3E, DEC: 360411295831363889B833334B57303D, Dome: 320F243558313733F09C33334B573026), site lat/lon/elec, park position, guider settings
- **config/state.json**: Persisted state — dec_offset, dome_offset, hra_encoder_zero_bias_arcsec, minor_hra_adj, minor_dec_adj, dec_home_deg (+29:37:59.9 fallback)
- **config/limits.json**: Motion limits (min_alt: 45°, max_alt: 89°, min_dec: -50°, max_dec: 70°), environment limits, camera limits
- **config/slip_calibration.json**: Slip/deadband coefficients per speed tier for RA/DEC; used by SlewEngine _calc_axis_speed_dir
- **.env**: TELESCOPE_MODE=REAL, ALPACA_HOST=0.0.0.0, ALPACA_PORT=11111, SLEW_SPEED_TRANSITION_DELAY_SEC=3, DOME geometry constants

### Relay Protocol

- **7-byte payload**: [c_rah, c_ral, c_dech, c_decl, c_dome, c_acc, c_console]
- **Protocol string**: `:U<c_rah><c_ral><c_dech><c_decl><c_dome><c_acc><c_#>`
- Each byte is a raw nibble (0x00-0x0F) OR'd with 0x30 to produce ASCII character (0-9, A-F)
- Start marker: `:U` (0x3A, 0x55)
- End marker: `#` (0x23)
- Sent at 10Hz to DUO Mega 2560 Arduino
- HELD signals (RA/DEC motions): stay HIGH as long as button is held
- PULSE signals (Dome CW/CCW/OFF): go HIGH for one send cycle
- Track ON/OFF pulses held for 20 send cycles to match legacy controller timing

### Simulation Architecture (SIMULATION Mode)

When TELESCOPE_MODE=SIMULATION:
- SimulationEngine QThread runs instead of hardware polling
- Simulated RA/DEC position based on applied speeds
- Tracking adds true sidereal rate to simulated HA
- All telemetry emitted as if from real hardware
- SlewEngine still runs but on simulated position
- Safety mechanisms still active (altitude limits, etc.)
- Used for testing/development without physical hardware

### Frontend/Backend Boundary (Existing)

The existing system is **desktop-only** (PyQt6). There is no web frontend currently. The backend/archetecture is:

```
PyQt6 GUI (single-user, local machine)
        │
        │-- connects to serial hardware (Arduino R4s, DUO Mega 2560)
        │-- receives GPS NMEA data
        │-- receives weather UDP broadcasts
        │-- hosts Alpaca HTTP server (port 11111)
        │-- hosts WebSocket server (port 11112)
        │-- controls telescope via relay payload :UXXXXXXX#
```

The existing system has NO network authentication, NO authorization, and the frontend (PyQt6 widgets) directly controls hardware through the backend workers.

## Future Modernization Architecture

The modernization adds a web application layer between the user and the existing STCS system:

```
Scientist/Admin Laptop
        │
        │  Modern Web Application (NEW)
        │  - Professional observatory-themed UI
        │  - Authentication + Authorization (backend enforced)
        │  - Role-based access (Admin / Scientist)
        │  - Responsive (laptop/desktop)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  API Gateway / Backend (NEW but controlled)                     │
│  │                               │                             │
│  │  ── Authentication Layer       │── JWT / Session              │ │
│  │  ── Authorization Layer        │── Role-based access control  │ │
│  │  ── Data Privacy Layer         │── Observation ownership      │ │
│  │  ── Session Management         │── Active session tracking    │ │
│  ▼                               ▼                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  STCS Backend Integration      │── Read-only telemetry       │ │
│  │  ── Pass-through to existing  │── Via existing workers      │ │
│  │    STCS Core, Drivers         │    (TelemetryWorker,       │ │
│  │                               │     MountCoordinator,     │ │
│  │                               │     AlpacaServer,         │ │
│  │                               │     TelemetryServer)     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                       │                                     │
│                       │                                     │
│                       ▼                                     │
│               Existing STCS V1 Desktop                        │
│               (PRESERVE UNCHANGED — all source unchanged)     │
│                                                             │
└─────────────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions (Why)

1. **Backend is authoritative** — All telescope commands, safety checks, and data access go through the existing STCS Core. The web frontend never sends raw commands to Arduino or serial port.

2. **Existing workers remain the integration point** — The new web backend will connect to the same background workers (TelemetryWorker, MountCoordinator, AlpacaServer, TelemetryServer) that the existing PyQt6 GUI uses. This minimizes new code and leverages existing, tested logic.

3. **Safety interlocks preserved** — All existing safety (altitude limits, slew engine reversal protection, cooldowns) remain active when web commands flow through the same paths.

4. **No direct hardware access from browser** — The web frontend sends validated commands to the backend, which routes them through existing STCS logic. This follows RULE 4: "Never allow browser/frontend to directly control physical telescope hardware."

5. **Simulation-first approach** — Telescope control in early modernized phases operates in SIMULATION mode (TELESCOPE_MODE=SIMULATION), with REAL mode integration only after thorough testing (Phase 6+).

6. **Observation ownership at database level** — Future PostgreSQL database enforces Scientist A cannot access Scientist B's data. Frontend hiding is supplementary only; the backend API must enforce privacy.

7. **Environment variables for all configuration** — No hard-coded credentials. All database hosts, ports, usernames, and passwords via .env files. .env.example contains placeholders only.

8. **Combined security model** — Network + Authentication + Authorization + Device/Session controls. Same Wi-Fi is NOT a sufficient security boundary.

9. **Clear OVERVIEW → DETAILS → CONTROL priority** — UI design prioritizes safety-critical information first, then details, then controls.

10. **Small, reversible changes** — Each phase adds functionality that can coexist with the existing system. No destructive migrations or overwrites.

### Frontend/Application Boundary

The modernized web application will have this boundary:

```
Web Frontend (NEW)                       Existing STCS Backend (PRESERVE)
│                                        │
│  ○ Telescope status display            │  ○ MotionState (thread-safe)
│  ○ Dome status display                 │  ○ SlewEngine (smart slew)
│  ○ Telemetry readout                   │  ○ Safety (altitude interlock)
│  ○ GPS position                        │  ○ AstrometryEngine (LST/AZ/EL)
│  ○ Weather information                 │  ○ LegacyDecoder (count→coord)
│  ○ Observatory information             │  ○ MountCoordinator (drivers)
│  ○ Observation history                 │  ○ ControlSerial (relay protocol)
│  ○ Control buttons (limited)           │  ○ SimulationEngine (SIM mode)
│                                        │  ○ Real hardware (REAL mode)
│                                        ▼
│                                        Existing PyQt6 GUI (unchanged)
```

### PostgreSQL Boundary (Future)

When PostgreSQL is integrated:
- Observation records stored with ownership (user_id → observation)
- API queries enforce privacy (Admin sees permitted, Scientist sees own only)
- Never hard-code credentials — environment variables only
- .env for local development, .env.example with placeholders
- Migration must be non-destructive; never drop/reset existing data

### Deployment Concept

The final deployed system will:

1. Run the modern web application on a server or laptop
2. Web app connects to existing STCS workers running on the same observatory network
3. Telescope hardware connected to same laptop (or separate control computer)
4. Authentication required for all access
5. Admin and Scientist roles with proper data privacy
6. All existing safety mechanisms active
7. Observation data stored in PostgreSQL with ownership
8. Export functionality (PDF, Excel, CSV) with privacy enforcement
9. Audit trail for administrator actions
10. Security-hardened configuration (no secrets in source, HTTPS where applicable)

## Important Architectural Decisions (Summary)

| Decision | Why |
|----------|-----|
| Backend authoritative | Prevents browser from bypassing safety; follows RULE 5 |
| Existing workers as integration points | Minimizes new code; leverages tested logic; follows RULE 2 |
| Simulation-first telescope control | Safe testing without physical hardware; follows RULE 20 |
| Observation ownership in database | Required for Scientist privacy; follows RULE 13 (clear separation) |
| Environment variables for all config | Security; follows RULE 8 (never expose secrets) |
| Combined security model (network + auth + authz + device) | Defense in depth; follows RULE 6 (frontend hiding not security) |
| OVERVIEW → DETAILS → CONTROL UI priority | Safety-critical info always obvious; follows RULE 18 (useful comments) |
| Never break existing working telescope/hardware | Primary project principle; follows RULE 1 |
| Preserve existing STCS desktop application | Non-negotiable; follows RULE 16 |