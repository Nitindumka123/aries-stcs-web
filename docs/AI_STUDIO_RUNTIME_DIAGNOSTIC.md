# AI Studio Runtime Diagnostic: ARIES 104 cm Sampurnanand Telescope Backend Architecture

**Observatory Facility:** ARIES 104 cm Sampurnanand Optical Telescope  
**Location:** Manora Peak, Nainital, Uttarakhand, India (29.3619° N, 79.4581° E, Elev. 1,927 m)  
**System Under Test:** STCS Web Interface (v1.4) running within Google AI Studio Cloud Run Container  
**Date of Diagnostic Assessment:** 2026-09-09  
**Status:** COMPLETED & VERIFIED  

---

## 1. Executive Summary & Diagnostic Verdict

A comprehensive architectural and diagnostic audit of the ARIES 104 cm Sampurnanand Telescope Control System (STCS) web application was conducted within the Google AI Studio containerized runtime.

### Diagnostic Findings Summary

| Subsystem / Dependency | Target Address / Interface | Container Runtime State | Graceful Degradation Strategy |
| :--- | :--- | :--- | :--- |
| **PostgreSQL Database** | `localhost:5432` (`stcs_observatory`) | **UNAVAILABLE** (`ECONNREFUSED`) | Development fallback store with standard credentials (`Admin`, `Scientist1`, `operator`). UI displays prominent `DATABASE UNAVAILABLE` banner. |
| **STCS Hardware Bus** | Serial / RS-232 / TCP loopback | **DISCONNECTED** (`ECONNREFUSED`) | Telemetry returns `DISCONNECTED` / `NOT_AVAILABLE`. Command safety gate active (`STCS_COMMANDS_ENABLED=0`). |
| **CCD Camera Subsystem** | Princeton Instruments LightField / Alpaca (Port 11111) | **ABSENT** (`ECONNREFUSED`) | Explicit `SIMULATION MODE` active with synthetic starfield preview and download capabilities; clearly labeled to avoid misrepresentation. |
| **Weather Sensors** | Davis Vantage Pro2 UDP/WS (Port 11112) | **OFFLINE** | Unreachable metrics explicitly output `NOT_AVAILABLE`; no fabricated false telemetry. |
| **HTTP Web Routes** | Port 3000 (Express / EJS) | **OPERATIONAL (100% 200 OK)** | All uncaught exceptions and `ReferenceError` crashes (`limit`, `cam_status`) resolved. |

---

## 2. Google AI Studio Container Runtime Environment Assessment

### 2.1 Sandboxed Execution Environment
The AI Studio runtime is an isolated Linux container hosted on Google Cloud Run:
- **Operating System:** Linux (`container-host`)
- **Node.js Engine:** v22.23.2
- **Network Exposure:** Port 3000 is the **sole externally accessible port** routed through an nginx reverse proxy layer.
- **Hardware Isolation:** The container has no physical interfaces:
  - No access to local RS-232 / USB serial ports (`/dev/ttyS*`, `/dev/ttyUSB*`).
  - No access to physical relay hardware, Arduino microcontrollers, or stepper drive motors.
  - No access to local observatory network ports (Alpaca port 11111, Davis weather port 11112, PostgreSQL port 5432).

### 2.2 Environment Configuration Audit
Analysis of `.env.example` vs runtime environment variables:
- `STCS_COMMANDS_ENABLED=0`: Correctly active by default. Commands are safely rejected before reaching hardware.
- `DB_HOST=localhost`, `DB_PORT=5432`: Configured to loopback, where no PostgreSQL daemon is running inside the application container.
- `PORT=3000`: Hardcoded by infrastructure constraints.

---

## 3. Service Connectivity & Root Cause Analysis

### 3.1 Authentication Failure Root Cause Analysis
**Observed Problem:**
Login attempts with `Scientist1` and `Admin` previously failed with:
`"Incorrect username or password"`

**Root Cause Analysis:**
1. The authentication module attempted to query PostgreSQL via the `pg` client pool.
2. Because PostgreSQL is unavailable in the container sandbox, the connection attempt threw an uncaught or unhandled `ECONNREFUSED` exception.
3. The legacy error handling trapped this database connection failure and coerced the outcome into a generic authentication rejection (`"Incorrect username or password"`).
4. **Architectural Flaw:** Infrastructure unavailability was misrepresented to operators as invalid operator credentials.

**Remediation:**
1. Implemented synchronous/asynchronous database availability pre-checks (`isPostgresAvailableSync()`).
2. If PostgreSQL is unavailable, the system switches to the authoritative `DEVELOPMENT_FALLBACK` user store.
3. The development fallback store contains verified SHA-256 password hashes for standard observatory roles:
   - `Admin` (Role: `admin`) &rarr; `Admin@123`
   - `Scientist1` (Role: `scientist`) &rarr; `Pass@123`
   - `operator` (Role: `operator`) &rarr; `operator123`
4. Login page now displays an explicit **POSTGRESQL UNAVAILABLE &middot; Development Fallback Store Active** indicator, preventing misrepresentation.

### 3.2 Telescope Hardware Bus Disconnection
**Observed Problem:**
Telescope mount showed `DISCONNECTED`, and commands returned `COMMANDS_DISABLED` (`STCS_COMMANDS_ENABLED=0`).

**Root Cause Analysis:**
- The STCS v1 telescope control system is physical observatory hardware at Manora Peak. In the isolated cloud container, no hardware serial or socket link exists.
- `STCS_COMMANDS_ENABLED` is intentionally set to `0` to protect physical machinery from unauthorized remote actuation.

**Remediation:**
- Built hardware-aware telemetry snapshots: when the hardware bus is unavailable, coordinates safely output `NOT_AVAILABLE` or null references, and tracking states display `DISCONNECTED`.
- The UI features an observatory safety banner indicating that commands cannot reach physical motors while `STCS_COMMANDS_ENABLED=0`.

### 3.3 Observation History HTTP 500 Error
**Observed Problem:**
Navigating to `/app/observations` yielded `Internal Server Error` (HTTP 500).

**Root Cause Analysis:**
- In `server.ts`, the pagination controller computed `pageSize = 15` and passed `page` and `total` to `res.render('observations')`, but omitted the variable `limit`.
- In `views/observations.ejs`, line 301 attempted to calculate `<% if (page * limit < total) { %>`.
- Node EJS engine threw: `ReferenceError: limit is not defined`, crashing the entire page.

**Remediation:**
1. Passed `limit: pageSize` from `server.ts` into the template payload.
2. In `views/observations.ejs`, fortified the expression to `<% if (page * (typeof limit !== 'undefined' ? limit : 15) < total) { %>`.
3. Added fallback support to memory-backed observation records when PostgreSQL is unreachable.

### 3.4 Camera Console HTTP 500 Error
**Observed Problem:**
Navigating to `/app/camera` produced an HTTP 500 error.

**Root Cause Analysis:**
- In `server.ts`, the camera controller rendered the template with property `camera_status`, whereas `views/camera.ejs` expected `cam_status.state`, `cam_status.temperature`, etc.
- Accessing `cam_status.state` when `cam_status` was undefined caused a fatal `ReferenceError: cam_status is not defined`.

**Remediation:**
1. Passed both `cam_status` and `camera_status` in `server.ts`.
2. Initialized a safe local alias `cs` in `views/camera.ejs` with complete structural defaults.
3. Added a prominent hardware warning banner: **CAMERA NOT AVAILABLE &middot; SIMULATION MODE**.
4. Watermarked the frame inspector preview canvas as **SIMULATED / SYNTHETIC** to comply with scientific integrity guidelines.

---

## 4. Operational Controls & Interface Verification

All required manual motion, dome, and calibration controls specified in observatory operational protocols have been implemented and verified:

### 4.1 Manual Motion Axis Speeds
- **Right Ascension (RA):**
  - `COARSE`
  - `FINE1`
  - `FINE2`
  - Directional Jog: `+RA (WEST)` / `-RA (EAST)`
- **Declination (DEC):**
  - `COARSE`
  - `FINE1`
  - `FINE2`
  - Directional Jog: `+DEC (NORTH)` / `-DEC (SOUTH)`

### 4.2 Dome Azimuth Controls
- `CW`: Rotate Dome Clockwise
- `CCW`: Rotate Dome Counter-Clockwise
- `STOP`: Halt Dome Rotation
- `SYNC`: Align Dome Azimuth to Mount Optical Axis
- `AUTO`: Toggle Automated Geometric Tracking

### 4.3 Calibration & Reference Setting Suite
- `DEC HOME`: Acquire/query DEC home limit switch reference
- `SET HOME`: Establish current mount position as Home reference
- `SET RA`: Apply absolute RA coordinate calibration (`HH:MM:SS`)
- `SET DEC`: Apply absolute DEC coordinate calibration (`±DD:MM:SS`)
- `SET DOME`: Apply absolute Dome encoder azimuth calibration (`0–360°`)
- `RA OFFSET`: Apply differential RA guide offset (seconds)
- `DEC OFFSET`: Apply differential DEC guide offset (arcseconds)
- `CLEAR OFFSETS`: Zero out all operational offsets

---

## 5. Automated Verification Matrix

Every primary user endpoint was systematically verified via internal HTTP integration tests:

```
[PASS] GET  /login                  HTTP 200 OK (Infrastructure status banner rendered)
[PASS] POST /api/login              HTTP 302 Redirect -> /app/control (Scientist1 verified)
[PASS] GET  /app/control            HTTP 200 OK (No crash; STCS Disconnected banner visible)
[PASS] GET  /app/observations       HTTP 200 OK (No crash; Database Unavailable banner visible)
[PASS] GET  /app/camera             HTTP 200 OK (No crash; Simulation Mode banner visible)
[PASS] GET  /app/system             HTTP 200 OK (No crash; Subsystems & Runtime Diag rendered)
[PASS] GET  /api/diagnostics        HTTP 200 OK (Machine-readable JSON diagnostic output)
```

---

## 6. Recommendations for Production vs Sandbox Deployment

1. **For Production Deployment at Manora Peak:**
   - Host PostgreSQL locally on the observatory subnet or configure secure credentials in `.env`.
   - Set `STCS_COMMANDS_ENABLED=1` only after physical interlocking checks and optical limit switch verification.
   - Connect the STCS v1 serial bus interface or Alpaca server daemon.
   - Install Princeton Instruments LightField software and connect the PIXIS 1024B camera over USB/GigE.

2. **For AI Studio Sandbox Testing:**
   - The application is now fully fault-tolerant and resilient.
   - Operators can sign in with `Scientist1 / Pass@123` or `Admin / Admin@123`.
   - All visual controls, forms, and diagnostic screens remain 100% interactive without triggering unhandled exceptions or HTTP 500 crashes.
