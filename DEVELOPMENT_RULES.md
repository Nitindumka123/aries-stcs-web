# DEVELOPMENT RULES

## Absolute Development Rules

These are the 20 non-negotiable development rules for this project. Every change must be evaluated against these rules. Violation of any rule requires STOPPING and reporting the risk before implementing the change.

### RULE 1: Never break existing working telescope/hardware communication
- Any change that could disrupt the existing PyQt6 GUI's ability to communicate with telescope hardware is prohibited
- The existing TelemetryWorker, MountCoordinator, and serial communication paths must continue to function
- **Test**: Existing `python stcs_v1\src\main.py` must still start and run without errors
- **Risk report required** before any change that touches worker threads, signal/slot connections, or serial port handling

### RULE 2: Never rewrite working telescope-control logic without necessity
- The existing logic in `motion_state.py`, `slew_engine.py`, `safety.py`, `astrometry.py`, and `legacy_decoder.py` is verified working
- Do not rewrite these modules unless absolutely necessary for the modernization
- If a rewrite is needed, the new code must produce identical output for identical input
- **Test**: Existing slew operations, safety blocks, and coordinate calculations must produce the same results
- **Risk report required** before rewriting any core telescope-control module

### RULE 3: Never bypass existing safety mechanisms
- The altitude safety guard (`safety.py`), slew engine reversal protection, and cooldown systems must remain fully active
- No new code path may bypass or disable existing safety checks
- Safety mechanisms must apply to all request sources (GUI, Web, API, CLI)
- **Test**: Safety blocks must trigger for the same conditions they currently block
- **Risk report required** before any change that could affect safety interlock behavior

### RULE 4: Never allow browser/frontend to directly control physical telescope hardware
- The web frontend must NEVER send commands directly to Arduino, serial port, or telescope motors
- All telescope commands from the web must flow through the existing STCS Core logic
- The backend gateway must be the sole interface to physical hardware
- **Risk report required** before any integration point that could allow direct hardware control from frontend

### RULE 5: Backend is authoritative
- The backend API must enforce all security, privacy, and safety rules
- The frontend must not be trusted for any security-critical decision
- All API requests are validated, authorized, and checked for safety before execution
- **Risk report required** before any change that reduces backend authority

### RULE 6: Frontend hiding is not security
- Hiding buttons, disabling controls, or hiding menu items in the frontend does NOT constitute security
- A determined attacker can always bypass frontend filtering via direct API calls
- All security restrictions must be enforced by the backend API and/or database
- **Risk report required** before any security claim that relies primarily on frontend measures

### RULE 7: Never fabricate real telemetry
- If hardware or a sensor is not connected, the application must show: Disconnected / Unavailable / Not connected
- Simulation data is acceptable only when explicitly operating in SIMULATION mode (TELESCOPE_MODE=SIMULATION)
- Never display fake coordinate values as if they were real
- **Risk report required** before any telemetry that could be mistaken for real hardware data

### RULE 8: Never expose secrets
- No passwords, database credentials, API keys, or serial numbers in source code
- No hard-coded .env files with real values committed to Git
- All secrets via environment variables only
- .env files must be in .gitignore
- **Risk report required** before any secret exposure

### RULE 9: Never hard-code passwords
- Development credentials (Admin/Admin@123, ScientistN/Pass@123) must never be hard-coded into Python source files
- If authentication is implemented in early phases, passwords must be securely hashed
- .env.example must contain placeholders only (e.g., `DB_PASSWORD=your_password_here`)
- **Risk report required** before any password hard-coding

### RULE 10: Never destroy existing database data without explicit approval
- If PostgreSQL is integrated, never run destructive migrations that drop tables or delete data
- Existing configuration data (config/settings.json, config/state.json) must be preserved
- Any database migration must be reversible
- **Risk report required** before any database migration

### RULE 11: Never perform destructive database migrations without approval
- All database schema changes must be additive (add tables/columns, never drop)
- If renaming/refactoring columns, data must be migrated, not dropped
- Backup existing data before any migration
- **Risk report required** before any migration step

### RULE 12: Test every phase before moving forward
- Each phase must have passing tests before the next phase begins
- Existing STCS V1 functionality must be preserved (regression testing)
- Safety mechanisms must be tested at each phase
- **Risk report required** before moving to next phase without test verification

### RULE 13: Keep implemented/planned/future/unverified functionality clearly separated
- Use clear labeling in all documentation:
  - "Implemented and Verified in Source"
  - "Documented But Not Verified"
  - "Planned"
  - "Future"
  - "Unknown"
- If documentation and source code disagree, SOURCE CODE WINS
- Document discrepancies instead of silently changing the facts
- **Risk report required** before any ambiguity between documented and implemented functionality

### RULE 14: Inspect actual source code before assuming functionality exists
- Do not assume a feature exists because documentation says so
- Search the actual repository source code to verify
- If not found in source, classify as "Unknown" or "Planned," not "Implemented"
- **Risk report required** before assuming functionality that is not verified in source

### RULE 15: Make small, reversible changes
- Implement features in the smallest possible increment
- Each change should be reversible (can undo without affecting other functionality)
- Avoid large-scale refactoring that touches many interdependent modules
- **Risk report required** before any change that touches more than 3 related modules simultaneously

### RULE 16: Preserve the existing STCS desktop application
- The existing PyQt6 desktop GUI at `stcs_v1/src/main.py` must continue to work unchanged
- No existing source files may be modified in a way that breaks the desktop application
- The desktop application is the fallback and reference implementation
- **Risk report required** before any change that modifies shared code used by both desktop and web

### RULE 17: New functionality must coexist with the existing STCS system
- New web application features must coexist with the existing desktop system
- Both can run simultaneously; the web does not replace the desktop
- The existing system is the authoritative reference for all telescope control logic
- **Risk report required** before any new functionality that could conflict with existing behavior

### RULE 18: Use useful comments to explain WHY important architectural decisions exist
- Comments should explain WHY, particularly around:
  - Hardware boundaries
  - Safety mechanisms
  - Authentication and authorization
  - Data ownership
  - Session handling
  - Simulation mode
  - STCS integration
  - Telescope commands
  - Future hardware integration
- Do not fill code with unnecessary comments
- **Risk report required** before code lacking useful architectural comments

### RULE 19: Never make a major architectural change simply because a newer framework is popular
- Technology choices must serve the project requirements, not popularity
- Framework choices (FastAPI, Flask, React, etc.) must be justified by project needs
- The existing PyQt6 system works; any new framework must add capability, not just replace
- **Risk report required** before any major framework change without clear project benefit

### RULE 20: If a change could affect physical hardware behavior, STOP and report the risk before implementing it
- Any change that could modify how the telescope moves, the dome operates, or the relays function
- Any change to serial communication, relay payload format, or motor control logic
- Any change to safety limits, thresholds, or timing
- **STOP immediately** — document the risk, assess impact, report before proceeding
- This is the most critical rule for physical telescope safety

## Hardware Protection Rules

| Rule | Description |
|------|-------------|
| HP-1 | No code change may alter the 7-byte relay payload format (:UXXXXXXX# protocol) without explicit approval and testing |
| HP-2 | No change to serial port baud rate, timeout, or port discovery logic without risk assessment |
| HP-3 | No change to DUO Mega 2560 command timing (10Hz relay packet rate) without testing |
| HP-4 | No change to MountCoordinator offset persistence logic without backup and verification |
| HP-5 | No change to emergency stop behavior or cooldown sequence without safety test |

## Safety Rules

| Rule | Description |
|------|-------------|
| SR-1 | Altitude safety floor (min_altitude_deg = 45°) must never be disabled or lowered without approval |
| SR-2 | Slew engine reversal protection (dead-band hysteresis, cooldown timers) must remain fully active |
| SR-3 | Motor cooldown after slew (6-second default) must always be enforced |
| SR-4 | Emergency stop must clear ALL motion (RA, DEC, slew state) regardless of context |
| SR-5 | Dome safety (wind, rain limits) must remain configured and checked |

## Database Rules

| Rule | Description |
|------|-------------|
| DB-1 | Never hard-code database credentials in Python source files |
| DB-2 | Use environment variables for all database connection parameters |
| DB-3 | Use .env for local development; .env.example with placeholders only |
| DB-4 | Ensure .env is not committed to Git (gitignore) |
| DB-5 | Never run destructive migrations without explicit approval |
| DB-6 | All observation records must have clear ownership (user_id field) |
| DB-7 | Admin can access permitted observations; Scientist can access only own |

## Security Rules

| Rule | Description |
|------|-------------|
| SEC-1 | Combined security model: Network + Authentication + Authorization + Device/Session |
| SEC-2 | Same Wi-Fi is NOT a sufficient security boundary |
| SEC-3 | Backend is authoritative for all security decisions |
| SEC-4 | Frontend hiding is NOT security |
| SEC-5 | No hard-coded passwords or secrets in source code |
| SEC-6 | All API endpoints validate authentication |
| SEC-7 | All data queries enforce observation ownership |
| SEC-8 | Input validation on all API requests |
| SEC-9 | Rate limiting on API endpoints |
| SEC-10 | Audit logging for all significant events |

## Testing Rules

| Rule | Description |
|------|-------------|
| T-1 | Test every phase before moving forward |
| T-2 | Existing STCS V1 functionality must be preserved (regression testing) |
| T-3 | Safety mechanisms must be tested at each phase |
| T-4 | Authentication/authorization tested for both Admin and Scientist roles |
| T-5 | Observation privacy enforced (Scientist A cannot access Scientist B's data) |
| T-6 | Export formats respect ownership boundaries |
| T-7 | Simulation mode used for all control function testing until Phase 6 |
| T-8 | Never test by connecting to physical hardware during early phases |

## Documentation Rules

| Rule | Description |
|------|-------------|
| D-1 | Keep implemented/planned/future/unverified clearly separated |
| D-2 | If documentation and source code disagree, source code wins |
| D-3 | Use useful comments to explain WHY architectural decisions exist |
| D-4 | Document discrepancies between documentation and source |
| D-5 | Phase ordering principle: UNDERSTAND → DOCUMENT → FOUNDATION → ... |
| D-6 | Report all risks before implementing potentially-affecting changes |

## Source-Code Verification Rules

| Rule | Description |
|------|-------------|
| V-1 | Inspect actual repository source code before assuming functionality |
| V-2 | Grep/read multiple files to verify code paths |
| V-3 | If not found in source, classify as "Unknown," not "Implemented" |
| V-4 | Discrepancies between docs and source must be documented |
| V-5 | Authoritative source is the repository at project root C:\Users\dumka\OneDrive\Desktop\GUI |

## Change-Management Rules

| Rule | Description |
|------|-------------|
| C-1 | Before modifying any file, check Git status and report changes |
| C-2 | Never overwrite unrelated existing changes |
| C-3 | Do not commit anything automatically |
| C-4 | Do not delete user-created files |
| C-5 | Do not modify the existing .venv directory |
| C-6 | Report every file created, modified, or deleted |
| C-7 | If Git is available, `git diff` must show only intended changes |
| C-8 | Changes that could affect physical hardware must follow RULE 20 (STOP and report risk) |

## Most Important Final Instruction

**Rule 20 supersedes all others.** If a change could affect physical hardware behavior, STOP and report the risk before implementing it. This is the most critical rule for physical telescope safety. No exception without explicit approval and comprehensive risk assessment.