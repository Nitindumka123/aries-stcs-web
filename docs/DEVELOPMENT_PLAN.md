# DEVELOPMENT PLAN

## Overview

This document defines the complete multi-phase development roadmap for the ARIES STCS modernization project. The plan is additive and incremental — the existing STCS V1 desktop PyQt6 application must remain functional and unchanged throughout all phases.

All phases are documented here for future reference. **DO NOT implement these phases now.** This phase (Phase 0) is documentation only.

## Phase Ordering Principle

The safe development progression follows:

UNDERSTAND → DOCUMENT → FOUNDATION → AUTHENTICATION → UI SHELL → READ-ONLY DATA → DASHBOARD → SIMULATION CONTROL → REAL HARDWARE INTEGRATION → ADVANCED FEATURES → SECURITY HARDENING → TESTING → DEPLOYMENT

Never jump directly from UI development to physical telescope control.

## Phase Descriptions

### PHASE 0
**Project understanding + permanent documentation** (CURRENT)

- Inspect actual repository source code (COMPLETED)
- Create permanent documentation files (PROJECT_CONTEXT.md, DEVELOPMENT_PLAN.md, ARCHITECTURE.md, SECURITY_MODEL.md, DEVELOPMENT_RULES.md)
- Create .env.example with placeholders only
- Verify existing system preservation
- Document all discrepancies between documentation and source

**Deliverables**: PROJECT_CONTEXT.md, DEVELOPMENT_PLAN.md (draft), initial ARCHITECTURE.md, SECURITY_MODEL.md, DEVELOPMENT_RULES.md, .env.example

---

### PHASE 1
**Application foundation + authentication + protected application shell**

- Add authentication backend (JWT or session-based)
- Create protected application shell that requires login
- Implement Admin/Scientist user roles
- Integrate with existing STCS system without modifying core logic
- Add .env.example with placeholder credentials (NOT real passwords)
- Setup PostgreSQL connection infrastructure (environment variables only, no tables yet)
- **Deliverable**: Login-protected web application shell with role-based access

### PHASE 2
**Professional UI/UX system + observatory interface**

- Design and implement professional observatory-themed UI
- Overview dashboard with system status summary
- responsive layout for laptop/desktop use
- Clear status and safety indicators
- **Deliverable**: Professional UI shell matching observatory/scientific software appearance

### PHASE 3
**Read-only telemetry integration**

- Integrate read-only telemetry from existing workers
- Telemetry broadcast (10Hz): RA, DEC, HRA, LST, Alt, Az, dome state, tracking, safety state, weather
- GPS status and position
- Weather temperature, humidity
- Alpaca telescope status (via existing Alpaca server)
- **Deliverable**: Read-only telemetry web display — scientist can view real system state

### PHASE 4
**Observatory dashboard + system health + climate/environment information**

- Full observatory dashboard combining all telemetry
- System health summary
- Climate/environment information panel
- GPS/LST information
- **Deliverable**: Complete observatory dashboard with all available telemetry

### PHASE 5
**Telescope control in simulation/safe mode**

- Add telescope control in SIMULATION mode only
- Slew to targets, track, move dome, etc. — all simulated
- Safety interlocks remain active even in simulation
- **Deliverable**: Telescope control in simulation mode for testing/development

### PHASE 6
**Integration with existing physical telescope-control system**

- Connect control backend to existing STCS Core and drivers
- Route web commands through existing MotionState → SlewEngine → ControlSerial path
- Ensure all safety mechanisms remain active
- **Deliverable**: Web-based telescope control that goes through existing STCS hardware path (simulation first, then REAL mode integration)

### PHASE 7
**Dome control + telescope/dome synchronization**

- Web-based dome control (CW/CCW/OFF, sync)
- Telescope-dome synchronization (auto-track sync functionality)
- **Deliverable**: Web interface for dome control with synchronization

### PHASE 8
**GPS + LST + astronomical information**

- Display GPS status and position
- LST (Local Sidereal Time) display
- Astronomical coordinates and information
- **Deliverable**: GPS/LST/astronomical information on dashboard

### PHASE 9
**Weather/environment + safety integration**

- Weather telemetry from existing WeatherWorker
- Safety state visualization
- Weather-induced dome actions (where configured)
- **Deliverable**: Weather/environment panel with safety integration

### PHASE 10
**Camera + observation workflow**

- Camera control interface (where LightField hardware exists)
- Observation initiation workflow
- **Deliverable**: Camera/observation workflow (mock mode where real hardware not available)

### PHASE 11
**Cartes du Ciel / target workflow**

- Integration with Cartes du Ciel telescope interface
- Target selection and slew planning
- **Deliverable**: Cartes du Ciel integration for target acquisition

### PHASE 12
**Observation history + PostgreSQL + ownership/privacy**

- PostgreSQL database setup with observation records
- Ownership/privacy enforcement at database level
- Observation list, search, filter
- **Deliverable**: Observation history with PostgreSQL-backed ownership/privacy

### PHASE 13
**PDF / Excel / CSV export + research data management**

- Export observation data in PDF, Excel, CSV formats
- Admin can download permitted/all observation data
- Scientists can download only their own data
- **Deliverable**: Export functionality with privacy enforcement

### PHASE 14
**Logs + audit trail**

- System logs storage
- Audit trail for administrator actions
- Observation action logging
- **Deliverable**: Logs and audit trail system

### PHASE 15
**Advanced observatory features**

- Advanced features as identified and prioritized
- **Deliverable**: Advanced features implementation

### PHASE 16
**Security hardening**

- Security audit and hardening
- Authentication token security
- Authorization boundary enforcement
- API security
- **Deliverable**: Hardened security model

### PHASE 17
**Complete software testing**

- Unit tests, integration tests, end-to-end tests
- Safety mechanism verification
- **Deliverable**: Complete test suite passing

### PHASE 18
**Physical hardware validation + deployment**

- Physical telescope validation
- Observatory deployment
- User acceptance testing
- **Deliverable**: Production-ready deployed system

## Goals by Phase

| Phase | Primary Goal |
|-------|-------------|
| 0 | Project understanding + permanent documentation |
| 1 | Authentication + protected application shell |
| 2 | Professional UI/UX system |
| 3 | Read-only telemetry integration |
| 4 | Observatory dashboard + system health |
| 5 | Telescope control in simulation mode |
| 6 | Integration with existing physical telescope-control system |
| 7 | Dome control + telescope/dome synchronization |
| 8 | GPS + LST + astronomical information |
| 9 | Weather/environment + safety integration |
| 10 | Camera + observation workflow |
| 11 | Cartes du Ciel / target workflow |
| 12 | Observation history + PostgreSQL + ownership/privacy |
| 13 | PDF / Excel / CSV export + research data management |
| 14 | Logs + audit trail |
| 15 | Advanced observatory features |
| 16 | Security hardening |
| 17 | Complete software testing |
| 18 | Physical hardware validation + deployment |

## Dependencies

- **Phase 1** must complete before any UI work (authentication required)
- **Phase 3** requires Phase 1 (authenticated telemetry access)
- **Phase 5** requires Phase 3 (telemetry foundation)
- **Phase 6** requires Phase 5 (simulation control foundation)
- **Phase 7** requires Phase 4 (dashboard with dome integration)
- **Phase 12** requires Phase 1 (authenticated PostgreSQL access)
- **Phase 13** requires Phase 12 (database-backed observation ownership)
- **Phase 16** should occur after Phase 17 (security hardening after testing)

## Deliverables Summary

| Deliverable | Phase | Description |
|-------------|-------|-------------|
| PROJECT_CONTEXT.md | 0 | Project purpose, structure, verified functionality, constraints |
| DEVELOPMENT_PLAN.md | 0 | Complete phases, goals, dependencies, deliverables, phase ordering |
| ARCHITECTURE.md | 0 | Existing architecture discovered from source, future modernization |
| SECURITY_MODEL.md | 0 | Network security, authentication, authorization, observation ownership |
| DEVELOPMENT_RULES.md | 0 | All non-negotiable development rules |
| .env.example | 0 | Environment variable placeholders (no real secrets) |
| Login-protected web app shell | 1 | Authentication, role-based access (Admin/Scientist) |
| Professional UI shell | 2 | Observatory-themed professional interface |
| Read-only telemetry display | 3 | 10Hz telemetry broadcast visualization |
| Observatory dashboard | 4 | Complete dashboard with all available telemetry |
| Simulation telescope control | 5 | Telescope control in SIMULATION mode only |
| Web telescope control (REAL) | 6 | Control through existing STCS hardware path |
| Dome control interface | 7 | Web-based dome CW/CCW/OFF and sync |
| GPS/LST/astronomical panel | 8 | GPS status, LST, coordinate display |
| Weather/safety panel | 9 | Weather telemetry with safety integration |
| Camera/observation workflow | 10 | Camera control (mock where hardware absent) |
| Cartes du Ciel integration | 11 | Target selection and slew planning |
| Observation history (PostgreSQL) | 12 | Ownership/privacy-backed observation records |
| PDF/Excel/CSV export | 13 | Format exports with privacy enforcement |
| Logs + audit trail | 14 | System logs and administrator audit trail |
| Advanced features | 15 | Prioritized advanced functionality |
| Security hardening | 16 | Security audit and reinforcement |
| Complete test suite | 17 | Unit + integration + end-to-end tests |
| Production deployment | 18 | Physical validation and observatory deployment |

## Testing Requirements

- Every phase must be tested before moving forward
- Safety mechanisms must be verified at each step
- Existing STCS V1 desktop functionality must be preserved — regression testing
- Authentication/authorization must be tested for both Admin and Scientist roles
- Observation privacy must be enforced (Scientist A cannot access Scientist B's data)
- Export formats must respect ownership boundaries
- Never test by connecting to physical hardware during early phases
- Simulation mode must be used for all control function testing until Phase 6

## Current vs Future Work Distinction

**CURRENT (Phase 0)**: Documentation only. No code modifications to existing functionality.

**FUTURE (Phases 1-18)**: New web application, authentication, database integration, modern UI. These will be implemented sequentially after Phase 0 review.

**Must Always Preserve**:
- Existing PyQt6 desktop application (stcs_v1/src/main.py and all source)
- Existing telescope-control logic (motion_state.py, slew_engine.py, safety.py, etc.)
- Existing serial communication (control_serial.py, mount_coordinator.py)
- Existing Arduino relay protocol
- Existing safety interlocks
- Existing Alpaca server (port 11111)
- Existing WebSocket telemetry server (port 11112)
- Existing GPS worker
- Existing weather worker
- Existing Alpaca coordination

## Explicit Distinctions

- **Implemented and Verified in Source**: Features present in stcs_v1/src/ and verified working
- **Documented But Not Verified**: Features mentioned in README/PROJECT_MAP that source code partially supports
- **Planned**: Features in the development plan (Phases 1-18) to be implemented later
- **Future**: Features beyond the documented roadmap
- **Unknown**: Features whose existence could not be confirmed from source code

**Rule**: If documentation and source code disagree, SOURCE CODE WINS. Document the discrepancy instead of silently changing the facts.