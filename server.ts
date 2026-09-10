import express, { Request, Response, NextFunction } from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import path from 'path';
import {
  findUserByUsername,
  verifyPassword,
  createUser,
  setPassword,
  listPendingUsers,
  approveUser,
  generateCsrfToken,
  authenticateUser
} from './src/auth.js';
import {
  isPostgresAvailableSync,
  isStcsAvailableSync,
  runRuntimeDiagnostics
} from './src/runtime-diagnostics.js';
import {
  SITE_LAT,
  SITE_LON,
  ALT_FLOOR,
  ALT_MAX,
  ENV_THRESHOLDS,
  isCommandsEnabled,
  getTelemetrySnapshot,
  executeCommand,
  acquireControlLock,
  releaseControlLock,
  getMountDetails
} from './src/observatory.js';
import {
  getAllObservations,
  getObservationById,
  deleteObservation,
  getObservationsSummary,
  getScientistStats,
  getAudit,
  getFileById
} from './src/store.js';
import {
  getCameraStatus,
  connectCamera,
  disconnectCamera,
  acquireFrame,
  abortAcquisition
} from './src/camera.js';

declare module 'express-session' {
  interface SessionData {
    user?: {
      id: number;
      username: string;
      role: string;
    };
    csrfToken?: string;
  }
}

const app = express();
const PORT = 3000;

app.set('view engine', 'ejs');
app.set('views', path.join(process.cwd(), 'views'));

app.use('/static', express.static(path.join(process.cwd(), 'static')));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use(cookieParser());
app.use(
  session({
    secret: 'aries-stcs-104cm-secret-key',
    resave: false,
    saveUninitialized: false,
    cookie: {
      httpOnly: true,
      secure: false,
      maxAge: 86400000
    }
  })
);

// CSRF token generation & validation middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  if (!req.session.csrfToken) {
    req.session.csrfToken = generateCsrfToken();
  }
  res.locals.csrf_token = req.session.csrfToken;
  res.cookie('stcs_csrf_token', req.session.csrfToken, { sameSite: 'lax', path: '/' });
  next();
});

function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (!req.session.user) {
    // If API request, return 401
    if (req.path.startsWith('/api/')) {
      return res.status(401).json({ error: 'Authentication required' });
    }
    return res.redirect('/login');
  }
  next();
}

function requireAdmin(req: Request, res: Response, next: NextFunction) {
  if (!req.session.user || req.session.user.role !== 'admin') {
    if (req.path.startsWith('/api/')) {
      return res.status(403).json({ error: 'Admin privilege required' });
    }
    return res.redirect('/app/control');
  }
  next();
}

function getCommonViewData(req: Request, active: string, pageTitle: string) {
  const snap = getTelemetrySnapshot();
  const user = req.session.user || { username: 'guest', role: 'guest' };
  const commandsActive = isCommandsEnabled();

  const led = snap.telemetry_status === 'LIVE' ? 'ok' : snap.telemetry_status === 'STALE' ? 'warn' : 'bad';
  let alertCls = 'ok';
  let alertText = 'ALL SUBSYSTEMS NOMINAL';

  if (!commandsActive) {
    alertCls = 'warn';
    alertText = 'COMMANDS LOCKED &middot; STCS_COMMANDS_ENABLED=0 (safe software default)';
  }

  if (snap.safety.overall === 'WARNING') {
    alertCls = 'warn';
    alertText = snap.safety.limit_message || 'ENVIRONMENT WARNING';
  } else if (snap.safety.overall === 'CRITICAL') {
    alertCls = 'crit';
    alertText = snap.safety.limit_message || 'SAFETY LIMIT ACTIVE';
  }

  const dbAvailable = isPostgresAvailableSync();
  const stcsConnected = isStcsAvailableSync();

  return {
    page_title: pageTitle,
    active,
    username: user.username,
    role: user.role,
    csrf_token: req.session.csrfToken,
    snap,
    system_state: snap.system_state,
    mode: snap.mode,
    led,
    db_ok: dbAvailable,
    db_available: dbAvailable,
    db_host: process.env.DB_HOST || 'localhost',
    db_port: parseInt(process.env.DB_PORT || '5432', 10),
    db_name: process.env.DB_NAME || 'stcs_observatory',
    stcs_connected: stcsConnected,
    alert_cls: alertCls,
    alert_text: alertText,
    lst_hms: snap.time.lst_hms,
    commands_enabled: commandsActive ? 'YES' : 'NO'
  };
}

// Root Route
app.get('/', (req: Request, res: Response) => {
  if (req.session.user) {
    return res.redirect('/app/control');
  }
  res.redirect('/login');
});

// Login Routes
app.get(['/login', '/api/login'], (req: Request, res: Response) => {
  if (req.session.user) {
    return res.redirect('/app/control');
  }
  const dbAvailable = isPostgresAvailableSync();
  res.render('login', {
    csrf_token: req.session.csrfToken,
    error: req.query.err ? String(req.query.err) : null,
    db_available: dbAvailable,
    db_host: process.env.DB_HOST || 'localhost',
    db_port: parseInt(process.env.DB_PORT || '5432', 10),
    db_name: process.env.DB_NAME || 'stcs_observatory',
    store_type: dbAvailable ? 'PostgreSQL Database' : 'Development Fallback Store'
  });
});

app.post('/api/login', (req: Request, res: Response) => {
  const uStr = typeof req.body?.username === 'string' ? req.body.username.trim() : '';
  const pStr = typeof req.body?.password === 'string' ? req.body.password.trim() : '';
  const isApi = req.is('json') || (req.headers.accept && req.headers.accept.includes('application/json') && !req.headers.accept.includes('text/html'));

  const authResult = authenticateUser(uStr, pStr);

  if (!authResult.success) {
    console.warn(`[AUTH] Login failed for "${uStr}": ${authResult.errorMessage} (code: ${authResult.errorCode})`);
    if (isApi) {
      const statusCode = authResult.errorCode === 'EMPTY_CREDENTIALS' ? 400
        : (authResult.errorCode === 'ACCOUNT_PENDING' ? 403 : 401);
      return res.status(statusCode).json({
        error: authResult.errorMessage,
        errorCode: authResult.errorCode,
        storeType: authResult.storeType,
        databaseReachable: authResult.databaseReachable
      });
    }
    return res.redirect(`/login?err=${encodeURIComponent(authResult.errorMessage || 'Authentication failed')}`);
  }

  const user = authResult.user!;
  console.log(`[AUTH] Login successful for user: "${user.username}" (role: ${user.role}, store: ${authResult.storeType})`);

  req.session.user = {
    id: user.id,
    username: user.username,
    role: user.role
  };

  if (isApi) {
    return res.json({
      success: true,
      message: 'Authentication successful',
      storeType: authResult.storeType,
      user: {
        id: user.id,
        username: user.username,
        role: user.role
      },
      redirect: '/app/control'
    });
  }

  res.redirect('/app/control');
});

app.post('/api/logout', (req: Request, res: Response) => {
  req.session.destroy(() => {
    res.redirect('/login');
  });
});

// Navigation Pages
app.get('/app/control', requireAuth, (req: Request, res: Response) => {
  const common = getCommonViewData(req, 'control', 'Telescope Control');
  const snap = common.snap;
  const mount = getMountDetails();

  const env = {
    weather_status: snap.weather.status,
    weather_source: snap.weather.source,
    weather_age_fmt: `${snap.weather.age_s}s`,
    temperature: snap.weather.temperature,
    humidity: snap.weather.humidity,
    dew_point: snap.weather.dew_point,
    wind_speed: snap.weather.wind_speed,
    rain: snap.weather.rain,
    humidity_state: snap.weather.humidity && snap.weather.humidity > ENV_THRESHOLDS.max_humidity_percent ? 'CRITICAL' : 'SAFE',
    humidity_threshold: ENV_THRESHOLDS.max_humidity_percent,
    wind_state: snap.weather.wind_speed && snap.weather.wind_speed > ENV_THRESHOLDS.max_wind_speed_kmh ? 'WARNING' : 'SAFE',
    wind_threshold: ENV_THRESHOLDS.max_wind_speed_kmh,
    rain_state: snap.weather.rain ? 'CRITICAL' : 'SAFE',
    altitude_state: snap.mount.alt_deg < ALT_FLOOR ? 'WARNING' : 'SAFE'
  };

  res.render('control', {
    ...common,
    telemetry_age: `${snap.telemetry_age_s}s ago`,
    telemetry_source: snap.telemetry_source,
    ra_hms: snap.mount.ra_hms,
    dec_dms: snap.mount.dec_dms,
    hra_hms: snap.mount.hra_hms,
    az: `${snap.mount.az_deg}\u00b0`,
    alt: `${snap.mount.alt_deg}\u00b0`,
    lst_source: snap.time.lst_source,
    jd: snap.time.jd,
    motion_state: snap.mount.motion_state,
    tracking: snap.mount.tracking ? 'ON' : 'OFF',
    sidereal: snap.mount.sidereal,
    env,
    safety_limit_active: snap.safety.limit_active,
    safety_limit_message: snap.safety.limit_message,
    cooldown_active: snap.safety.cooldown_active,
    site_lat: `${SITE_LAT}\u00b0 N`,
    site_lon: `${SITE_LON}\u00b0 E`,
    dome_state: snap.dome.state,
    dome_az: `${snap.dome.az_deg}\u00b0`,
    dome_sync: snap.dome.sync,
    dec_home: mount.decHome,
    ra_off: mount.raOffset,
    dec_off: mount.decOffset,
    dome_off: mount.domeOffset,
    ra_speed: snap.mount.ra_speed,
    ra_direction: snap.mount.ra_direction,
    dec_speed: snap.mount.dec_speed,
    dec_direction: snap.mount.dec_direction,
    atpark: snap.mount.at_park,
    athome: snap.mount.at_home,
    cmd_result: req.query.cmd ? String(req.query.cmd) : null
  });
});

app.get('/app/observations', requireAuth, (req: Request, res: Response) => {
  const common = getCommonViewData(req, 'observations', 'Observations Archive');
  const user = req.session.user!;
  const page = parseInt(req.query.page as string) || 1;
  const q = (req.query.q as string) || '';
  const status_f = (req.query.status as string) || '';
  const date_from = (req.query.from as string) || '';
  const date_to = (req.query.to as string) || '';
  const owner_filter = user.role === 'admin' ? (req.query.owner as string) : user.username;

  const obsId = req.query.obs ? parseInt(req.query.obs as string) : null;
  const detail = obsId ? getObservationById(obsId) : null;

  const allFiltered = getAllObservations({
    q,
    status: status_f,
    from: date_from,
    to: date_to,
    owner: owner_filter
  });

  const pageSize = 15;
  const items = allFiltered.slice((page - 1) * pageSize, page * pageSize);
  const summary = getObservationsSummary();

  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const weekAgo = new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10);
  const monthAgo = new Date(now.getTime() - 30 * 86400000).toISOString().slice(0, 10);

  res.render('observations', {
    ...common,
    summary,
    q,
    status_f,
    date_from,
    date_to,
    owner_filter: req.query.owner || '',
    today,
    week_ago: weekAgo,
    month_ago: monthAgo,
    items,
    detail,
    page,
    limit: pageSize,
    total: allFiltered.length
  });
});

app.get('/app/camera', requireAuth, (req: Request, res: Response) => {
  const common = getCommonViewData(req, 'camera', 'Camera Console');
  const camStatus = getCameraStatus();

  res.render('camera', {
    ...common,
    cam_status: camStatus,
    camera_status: camStatus
  });
});

app.get('/app/system', requireAuth, (req: Request, res: Response) => {
  const common = getCommonViewData(req, 'system', 'System Status & Telemetry');
  const snap = common.snap;

  const env = {
    weather_status: snap.weather.status,
    weather_source: snap.weather.source,
    weather_age_fmt: `${snap.weather.age_s}s`,
    weather_age_s: snap.weather.age_s,
    temperature: snap.weather.temperature,
    humidity: snap.weather.humidity,
    dew_point: snap.weather.dew_point,
    wind_speed: snap.weather.wind_speed,
    rain: snap.weather.rain,
    weather_fields_available: ['Temperature', 'Relative Humidity', 'Dew Point', 'Wind Speed', 'Rain Flag'],
    weather_fields_unavailable: ['Solar Irradiance', 'Cloud Sensor IR'],
    humidity_state: snap.weather.humidity && snap.weather.humidity > ENV_THRESHOLDS.max_humidity_percent ? 'CRITICAL' : 'SAFE',
    humidity_threshold: ENV_THRESHOLDS.max_humidity_percent,
    wind_state: snap.weather.wind_speed && snap.weather.wind_speed > ENV_THRESHOLDS.max_wind_speed_kmh ? 'WARNING' : 'SAFE',
    wind_threshold: ENV_THRESHOLDS.max_wind_speed_kmh,
    rain_state: snap.weather.rain ? 'CRITICAL' : 'SAFE',
    altitude_state: (snap.mount.alt_deg != null && snap.mount.alt_deg < ALT_FLOOR) ? 'WARNING' : 'SAFE',
    altitude_floor: ALT_FLOOR
  };

  const audit = getAudit();
  const diagnostics = runRuntimeDiagnostics(false);

  res.render('system', {
    ...common,
    env,
    alt_floor: ALT_FLOOR,
    alt_max: ALT_MAX,
    site_lat: `${SITE_LAT}\u00b0 N`,
    site_lon: `${SITE_LON}\u00b0 E`,
    safety_limit_active: snap.safety.limit_active,
    cooldown_active: snap.safety.cooldown_active,
    env_thresholds: ENV_THRESHOLDS,
    audit,
    diagnostics
  });
});

// Diagnostic endpoint
app.get('/api/diagnostics', async (_req: Request, res: Response) => {
  const diag = await runRuntimeDiagnostics(true);
  res.json(diag);
});

app.get('/app/admin', requireAuth, requireAdmin, (req: Request, res: Response) => {
  const common = getCommonViewData(req, 'admin', 'Administration');
  const pending = listPendingUsers();

  res.render('admin', {
    ...common,
    pending
  });
});

// Telemetry & Polling APIs
app.get('/api/telemetry', (req: Request, res: Response) => {
  res.json(getTelemetrySnapshot());
});

app.get('/api/telemetry/snapshot', (req: Request, res: Response) => {
  const snap = getTelemetrySnapshot();
  res.json({
    ...snap,
    lst_hours: snap.time.lst_deg / 15,
    ra_hours: snap.mount.ra_deg / 15,
    dec_deg: snap.mount.dec_deg,
    az_deg: snap.mount.az_deg,
    alt_deg: snap.mount.alt_deg,
    lst_source: snap.time.lst_source,
    tracking: snap.mount.tracking,
    slewing: snap.mount.motion_state === 'SLEWING',
    weather: {
      values: {
        temp_c: snap.weather.temperature,
        humidity_pct: snap.weather.humidity,
        dew_point_c: snap.weather.dew_point,
        wind_speed_kmh: snap.weather.wind_speed,
        rain: snap.weather.rain
      }
    },
    environment: {
      weather_status: snap.weather.status,
      weather_age_fmt: `${snap.weather.age_s}s`,
      humidity_state: snap.weather.humidity > ENV_THRESHOLDS.max_humidity_percent ? 'CRITICAL' : 'SAFE',
      wind_state: snap.weather.wind_speed > ENV_THRESHOLDS.max_wind_speed_kmh ? 'WARNING' : 'SAFE',
      rain_state: snap.weather.rain ? 'CRITICAL' : 'SAFE',
      altitude_state: snap.mount.alt_deg < ALT_FLOOR ? 'WARNING' : 'SAFE'
    }
  });
});

// Command APIs
app.get('/api/command/status', (req: Request, res: Response) => {
  const snap = getTelemetrySnapshot();
  res.json({
    commands_enabled: isCommandsEnabled(),
    stcs_connected: true,
    control_lock: snap.control_lock
  });
});

app.post('/api/command/tracking', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'tracking', req.body);
  if (req.headers.accept?.includes('application/json') || req.is('application/json')) {
    return res.json(result);
  }
  res.redirect(`/app/control?cmd=${encodeURIComponent(result.message)}`);
});

app.post('/api/command/slew', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'slew', req.body);
  if (req.headers.accept?.includes('application/json') || req.is('application/json')) {
    return res.json(result);
  }
  res.redirect(`/app/control?cmd=${encodeURIComponent(result.message)}`);
});

app.post('/api/command/stop', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'stop', req.body);
  res.json(result);
});

app.post('/api/command/emergency-stop', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'emergency_stop', req.body);
  res.redirect(`/app/control?cmd=${encodeURIComponent(result.message)}`);
});

app.post('/api/command/park', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'park', req.body);
  res.json(result);
});

app.post('/api/command/dome', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'dome', req.body);
  res.json(result);
});

app.post('/api/command/manual', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'manual', req.body);
  res.json(result);
});

app.post('/api/command/calibration', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = executeCommand(user, 'calibration', req.body);
  if (req.headers.accept?.includes('application/json') || req.is('application/json')) {
    return res.json(result);
  }
  res.redirect(`/app/control?cmd=${encodeURIComponent(result.message)}`);
});

app.post('/api/command/lock/acquire', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const ok = acquireControlLock(user);
  res.redirect(`/app/control?cmd=${encodeURIComponent(ok ? 'Control lock acquired' : 'Lock busy')}`);
});

app.post('/api/command/lock/release', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  releaseControlLock(user);
  res.redirect('/app/control?cmd=Control%20lock%20released');
});

// Camera APIs
app.get('/api/camera/status', requireAuth, (req: Request, res: Response) => {
  res.json(getCameraStatus());
});

app.post('/api/camera/connect', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  res.json(connectCamera(user));
});

app.post('/api/camera/disconnect', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  res.json(disconnectCamera(user));
});

app.post('/api/camera/acquire', requireAuth, async (req: Request, res: Response) => {
  const user = req.session.user!.username;
  const result = await acquireFrame(user, req.body);
  res.json(result);
});

app.post('/api/camera/abort', requireAuth, (req: Request, res: Response) => {
  const user = req.session.user!.username;
  res.json(abortAcquisition(user));
});

app.get('/api/camera/observations', requireAuth, (req: Request, res: Response) => {
  const limit = parseInt(req.query.limit as string) || 10;
  const items = getAllObservations().slice(0, limit);
  res.json({
    total: items.length,
    items
  });
});

app.get('/api/camera/file/:id', requireAuth, (req: Request, res: Response) => {
  const fileId = parseInt(String(req.params.id));
  const file = getFileById(fileId);
  if (!file || !file.buffer) {
    return res.status(404).send('File not found');
  }
  res.setHeader('Content-Type', 'application/octet-stream');
  res.setHeader('Content-Disposition', `attachment; filename="${file.filename}"`);
  res.send(file.buffer);
});

// Observations APIs
app.get('/api/observations', requireAuth, (req: Request, res: Response) => {
  const items = getAllObservations();
  res.json({ total: items.length, items });
});

app.get('/api/observations/scientist/:name', requireAuth, (req: Request, res: Response) => {
  const items = getAllObservations({ owner: String(req.params.name) });
  res.json({ total: items.length, items });
});

app.post('/api/observations/delete/:id', requireAuth, (req: Request, res: Response) => {
  const id = parseInt(String(req.params.id));
  deleteObservation(id);
  res.redirect('/app/observations');
});

app.get('/api/history/export', requireAuth, (req: Request, res: Response) => {
  const fmt = (req.query.fmt as string) || 'csv';
  const obs = getAllObservations();

  if (fmt === 'csv') {
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename="stcs_observations.csv"');
    const header = 'ID,Target,RA_deg,DEC_deg,Start,End,Duration_s,Status,Owner,Notes\n';
    const rows = obs.map(o =>
      `"${o.id}","${o.target.replace(/"/g, '""')}","${o.ra_deg}","${o.dec_deg}","${o.start}","${o.end}","${o.duration_s}","${o.status}","${o.owner}","${(o.notes || '').replace(/"/g, '""')}"`
    ).join('\n');
    return res.send(header + rows);
  }

  // Excel / PDF fallback or json export
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Content-Disposition', `attachment; filename="stcs_observations.${fmt === 'xlsx' ? 'xlsx.json' : 'pdf.json'}"`);
  res.json(obs);
});

// Admin APIs
app.get('/api/admin/scientists', requireAuth, requireAdmin, (req: Request, res: Response) => {
  res.json(getScientistStats());
});

app.post('/api/admin/users', requireAuth, requireAdmin, (req: Request, res: Response) => {
  const { username, password, role } = req.body;
  if (username && password && role) {
    try {
      createUser(username, password, role);
    } catch (e) {}
  }
  res.redirect('/app/admin');
});

app.post('/api/admin/password', requireAuth, requireAdmin, (req: Request, res: Response) => {
  const { username, new_password } = req.body;
  if (username && new_password) {
    setPassword(username, new_password);
  }
  res.redirect('/app/admin');
});

app.post('/api/admin/approve', requireAuth, requireAdmin, (req: Request, res: Response) => {
  const { user_id, action } = req.body;
  const id = parseInt(user_id);
  if (id) {
    approveUser(id, action === 'approve');
  }
  res.redirect('/app/admin');
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`ARIES 104 cm STCS Web Observatory running on http://0.0.0.0:${PORT}`);
});
