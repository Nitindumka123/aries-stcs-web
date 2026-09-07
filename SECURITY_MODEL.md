# SECURITY MODEL

## Combined Security Model

The future system must use a combined security model with four layers:

1. **NETWORK** — Same Wi-Fi is NOT a sufficient security boundary
2. **AUTHENTICATION** — Every user must log in
3. **AUTHORIZATION** — Backend-enforced role-based access control
4. **DEVICE / SESSION CONTROLS** — Session management and device tracking

The fact that a laptop is connected to the observatory Wi-Fi must not automatically make the user trusted. Authentication must still be required. Authorization must be enforced by the backend. Data privacy must be enforced by the backend.

## Network Security

- **Same Wi-Fi is NOT sufficient** — Connecting to the observatory Wi-Fi does not automatically trust a user
- **Authentication required even on local network** — A user on the observatory Wi-Fi must still log in
- **API endpoints protected** — All backend APIs require valid authentication token/session
- **CORS must be restricted** — Current configuration allows `allow_origins=["*"]` but this must be restricted for production
- **No hard-coded secrets** — No API keys, passwords, or credentials in source code
- **Use environment variables** — All network configuration (hosts, ports) via .env files
- ** .env must NOT be committed to Git** — Listed in .gitignore

## Authentication

### User Categories

Two initial user categories exist:

**ADMIN**
- Full observatory application access
- Can access permitted observations belonging to all users
- Can perform all observational functionality
- Can download all permitted research data
- Can access admin logs and system information

**SCIENTIST**
- Must log in with own credentials
- Generally able to use same operational functionality as Admin
- Cannot view other Scientists' private observation history
- Cannot download other Scientists' private data
- Cannot access other Scientists' research files
- Privacy restrictions enforced by backend/database

### Authentication Requirements

- **Mandatory login** — No unauthenticated access to any functionality
- **Secure credential handling** — Passwords must be securely hashed; plaintext passwords must never be stored
- **Credentials must not be hard-coded into source code** — Use authentication backend
- **Credentials must not be exposed to browser/frontend code** — Backend only
- **Development credentials** (for local dev only):
  - Admin: Username: Admin, Password: Admin@123
  - ScientistN: Username: ScientistN, Password: Pass@123
- **Production credentials** — Must be properly hashed and stored in database
- **Session management** — Login creates authenticated session; logout invalidates session

### Authentication Flow

1. User submits credentials to login endpoint
2. Backend validates credentials against database (hashed passwords)
3. On success, authentication token (JWT or session ID) returned to client
4. Token included in Authorization header for subsequent API requests
5. Backend validates token on each request; unauthorized requests rejected with 401
6. Session can be invalidated on logout or admin-initiated revocation
7. Token has expiration; refresh mechanism as needed

## Authorization / Data Privacy

### Admin/Scientist Permissions

| Action | Admin | Scientist |
|--------|-------|-----------|
| Use telescope functionality | ✓ | ✓ |
| View telescope status | ✓ | ✓ |
| Use dome functionality | ✓ | ✓ (where permitted) |
| View GPS/time information | ✓ | ✓ |
| View weather/climate information | ✓ | ✓ |
| Perform observations | ✓ | ✓ |
| View observation history | ✓ (all users) | ✓ (own only) |
| Download observation data | ✓ (permitted/all) | ✓ (own only) |
| Download PDF data | ✓ (permitted/all) | ✓ (own only) |
| Download Excel data | ✓ (permitted/all) | ✓ (own only) |
| Download CSV data | ✓ (permitted/all) | ✓ (own only) |
| View other Scientists' private data | ✓ (permitted) | ✗ (blocked) |
| Access other Scientists' research files | ✓ (permitted) | ✗ (blocked) |
| Bypass privacy by manipulating frontend | ✗ (blocked at backend) | ✗ (blocked at backend) |

### Critical Security Principle

**Frontend hiding is NOT security.** 

- Hiding buttons or disabling frontend controls does NOT prevent authorized access
- All security restrictions MUST be enforced by the backend API
- A determined attacker can always bypass frontend filtering
- The backend must validate every request and enforce all permissions

### Observation Ownership Enforcement

```
Conceptual Flow:

User (authenticated) ──→ API Request → PostgreSQL Database
                          │
                          │   Ownership check
                          ▼
                ┌─────────────────────┐
                │   Is user permitted│
                │   to access this   │
                │   observation?     │
                └─────────────────────┘
                           │
           ┌───────────────┼───────────────────────┐
           │               │                       │
           ▼               ▼                       ▼
   Grant access    Deny access     Redirect to own data
   (200 OK)        (403 Forbidden)   (200 OK - own only)
```

### Per-User Data Isolation

- Each observation record in PostgreSQL has `user_id` field
- **Admin queries**: Can access observations where permitted (all users, or specific Scientists)
- **Scientist queries**: Can only access observations where `user_id` = current user's ID
- **API layer enforces** this — never rely on frontend filtering
- **Database layer** also enforces via Row Level Security (RLS) or application-level queries
- **Never** allow a Scientist to another Scientist's data by manipulating request parameters

### API Security

- All API endpoints require valid authentication
- Rate limiting on API requests (prevent brute force, abuse)
- Input validation on all incoming data (prevent injection, malformed commands)
- Error messages do not leak sensitive information (no stack traces to clients)
- CORS restricted to observatory-originated domains (not `allow_origins=["*"]` in production)
- HTTPS for all external communications
- Request logging for audit trail

### Session Security

- Authentication tokens have limited lifespan
- Tokens invalidated on logout
- Concurrent session limit per user (configurable)
- Session fixation protection (regenerate session ID after login)
- Dead man's switch logic (from existing TelemetryServer) adapted for web sessions
- If user closes browser without logout, session eventually expires

### Device / Session Controls

- Track authenticated sessions per user
- View active sessions from admin panel
- Revoke specific sessions (e.g., if device is lost)
- Dead man's switch: if client disconnects while commanding motion, emergency stop triggers
- Device identity registration (for future granular controls)

### Secrets Management

- **NEVER hard-code passwords, database credentials, or API keys in source code** (RULE 9)
- Use environment variables for all secrets
- .env for local development — included in .gitignore
- .env.example contains placeholders only — never real values
- Production secrets injected via deployment environment, not checked into version control
- Database passwords supplied but must never appear in source code

### Audit Requirements

- Log all authentication events (successful logins, failures)
- Log all authorization events (access granted/denied per user/observation)
- Log all telescope command events (who commanded what, when)
- Log all data access events (who retrieved which observation data)
- Log all data export events (who downloaded which data in what format)
- Store audit logs in database with user_id, timestamp, action, result
- Admin can view audit logs where authorized
- Logs support investigation of security incidents

### Backend Enforcement Requirements

1. **Every API endpoint** validates authentication before processing
2. **Every data query** enforces observation ownership/permissions
3. **Every telescope command** goes through MotionState safety interlocks
4. **No command** reaches Arduino/serial hardware without passing through existing STCS Core logic
5. **Safety interlocks** (altitude limits, slew engine protections) always active regardless of request source
6. **Data privacy** enforced at database/API level, not just frontend
7. **Secrets never in source** — all via environment variables
8. **Audit logging** enabled for all significant events
9. **Input validation** on all API requests (axis, direction, speed, coordinates)
10. **Rate limiting** to prevent abuse of telescope control API

### Future Device/Session Controls

- Authenticated session management per user
- Ability to view and revoke active sessions
- Device registration and identity tracking
- Granular permission refinement per device (future)
- Session timeout and automatic expiration
- Integration with observatory SSO (future)

## Summary of Security Principles

| Principle | Description |
|-----------|-------------|
| Combined security model | Network + Authentication + Authorization + Device/Session |
| Same Wi-Fi ≠ trust | Authentication required even on observatory network |
| Backend enforcement | All security restrictions enforced server-side |
| Frontend hiding ≠ security | Frontend can be bypassed; backend is authoritative |
| Observation privacy | Scientist A cannot access Scientist B's data |
| No hard-coded secrets | All credentials via environment variables |
| Audit logging | All significant events logged for investigation |
| Input validation | All API requests validated before processing |
| Rate limiting | Prevent brute force and abuse |
| Session management | Tokens expire; logout invalidates; revocation possible |