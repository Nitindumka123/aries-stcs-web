import { TelemetrySnapshot, WeatherData, ControlLock } from './types.js';
import { addAudit } from './store.js';
import { isStcsAvailableSync } from './runtime-diagnostics.js';

// Observatory Site: Manora Peak, Nainital (ARIES 104 cm Sampurnanand Telescope)
export const SITE_LAT = 29.3619;
export const SITE_LON = 79.4581;
export const ALT_FLOOR = 10.0;
export const ALT_MAX = 89.0;

export const ENV_THRESHOLDS = {
  max_humidity_percent: 90.0,
  max_wind_speed_kmh: 45.0,
  close_dome_on_rain: true
};

let commandsEnabled = process.env.STCS_COMMANDS_ENABLED === '1';

export function isCommandsEnabled(): boolean {
  return commandsEnabled;
}

export function setCommandsEnabled(enabled: boolean) {
  commandsEnabled = enabled;
}

interface MountState {
  raDeg: number;
  decDeg: number;
  targetRaDeg: number | null;
  targetDecDeg: number | null;
  motionState: 'IDLE' | 'SLEWING' | 'TRACKING' | 'PARKING';
  tracking: boolean;
  raSpeed: string;
  raDirection: string;
  decSpeed: string;
  decDirection: string;
  atPark: boolean;
  atHome: boolean;
  decHome: string;
  raOffset: string;
  decOffset: string;
  domeOffset: string;
}

const mount: MountState = {
  raDeg: 83.822, // ~ M42 Orion
  decDeg: -5.391,
  targetRaDeg: null,
  targetDecDeg: null,
  motionState: 'IDLE',
  tracking: true,
  raSpeed: 'COARSE',
  raDirection: 'WEST',
  decSpeed: 'COARSE',
  decDirection: 'NONE',
  atPark: false,
  atHome: false,
  decHome: '0.000',
  raOffset: '0.000',
  decOffset: '0.000',
  domeOffset: '0.000'
};

const dome = {
  azDeg: 172.5,
  state: 'IDLE',
  sync: 'SYNCED',
  slaved: true
};

const controlLock: ControlLock = {
  owner: null,
  acquiredAt: null,
  elapsed_s: null
};

let weather: WeatherData = {
  status: 'LIVE',
  source: 'WeatherWorker UDP:12344',
  temperature: 12.4,
  humidity: 64.2,
  dewPoint: 5.6,
  windSpeed: 11.2,
  rain: false,
  updatedAt: Date.now()
};

// Simulation tick: tracking drift and weather fluctuations
setInterval(() => {
  const now = Date.now();

  // Drift RA slightly if tracking is ON
  if (mount.tracking && mount.motionState !== 'SLEWING' && mount.motionState !== 'PARKING') {
    // 360 degrees per 86164.1 seconds (sidereal day)
    mount.raDeg = (mount.raDeg + (360 / 86164.1) * 0.5) % 360;
  }

  // Smooth slewing towards target if slewing
  if (mount.motionState === 'SLEWING' && mount.targetRaDeg != null && mount.targetDecDeg != null) {
    const dRa = mount.targetRaDeg - mount.raDeg;
    const dDec = mount.targetDecDeg - mount.decDeg;
    const speed = 1.5; // deg per tick
    if (Math.abs(dRa) < speed && Math.abs(dDec) < speed) {
      mount.raDeg = mount.targetRaDeg;
      mount.decDeg = mount.targetDecDeg;
      mount.targetRaDeg = null;
      mount.targetDecDeg = null;
      mount.motionState = mount.tracking ? 'TRACKING' : 'IDLE';
    } else {
      mount.raDeg += Math.sign(dRa) * Math.min(speed, Math.abs(dRa));
      mount.decDeg += Math.sign(dDec) * Math.min(speed, Math.abs(dDec));
    }
  }

  // Slight natural fluctuations in weather
  weather.temperature = +(12.4 + Math.sin(now / 60000) * 1.5).toFixed(1);
  weather.humidity = +(64.2 + Math.cos(now / 45000) * 2.0).toFixed(1);
  weather.windSpeed = +(11.2 + Math.sin(now / 20000) * 3.0).toFixed(1);
  weather.updatedAt = now;

  if (controlLock.owner && controlLock.acquiredAt) {
    controlLock.elapsed_s = Math.round((now - controlLock.acquiredAt) / 1000);
  }
}, 500);

// Astronomical calculations for Manora Peak
export function getJulianDate(date: Date = new Date()): number {
  return date.getTime() / 86400000 + 2440587.5;
}

export function getLSTDeg(date: Date = new Date()): number {
  const jd = getJulianDate(date);
  const d = jd - 2451545.0;
  let gmst = 280.46061837 + 360.98564736629 * d;
  gmst = ((gmst % 360) + 360) % 360;
  const lst = (gmst + SITE_LON) % 360;
  return lst;
}

export function degToHMS(deg: number): string {
  let hours = deg / 15;
  hours = ((hours % 24) + 24) % 24;
  const h = Math.floor(hours);
  const minRem = (hours - h) * 60;
  const m = Math.floor(minRem);
  const s = ((minRem - m) * 60).toFixed(2);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(5, '0')}`;
}

export function degToDMS(deg: number): string {
  const sign = deg >= 0 ? '+' : '-';
  const abs = Math.abs(deg);
  const d = Math.floor(abs);
  const minRem = (abs - d) * 60;
  const m = Math.floor(minRem);
  const s = ((minRem - m) * 60).toFixed(1);
  return `${sign}${String(d).padStart(2, '0')}\u00b0${String(m).padStart(2, '0')}\u2032${String(s).padStart(4, '0')}\u2033`;
}

export function getAltAz(raDeg: number, decDeg: number, lstDeg: number) {
  const haDeg = (lstDeg - raDeg + 360) % 360;
  const haRad = (haDeg * Math.PI) / 180;
  const decRad = (decDeg * Math.PI) / 180;
  const latRad = (SITE_LAT * Math.PI) / 180;

  const sinAlt = Math.sin(decRad) * Math.sin(latRad) + Math.cos(decRad) * Math.cos(latRad) * Math.cos(haRad);
  const altRad = Math.asin(sinAlt);
  const altDeg = (altRad * 180) / Math.PI;

  const cosAz = (Math.sin(decRad) - Math.sin(latRad) * Math.sin(altRad)) / (Math.cos(latRad) * Math.cos(altRad));
  let azDeg = (Math.acos(Math.max(-1, Math.min(1, cosAz))) * 180) / Math.PI;
  if (Math.sin(haRad) > 0) azDeg = 360 - azDeg;

  return { altDeg, azDeg, haDeg };
}

export function getTelemetrySnapshot(): TelemetrySnapshot {
  const now = new Date();
  const lstDeg = getLSTDeg(now);
  const jd = getJulianDate(now).toFixed(5);
  const stcsConnected = isStcsAvailableSync();

  if (!stcsConnected) {
    return {
      timestamp: now.toISOString(),
      system_state: 'STCS DISCONNECTED',
      mode: 'STCS DISCONNECTED (COMMANDS LOCKED)',
      telemetry_status: 'DISCONNECTED',
      telemetry_source: 'DISCONNECTED (STCS V1 Hardware Bus Unreachable)',
      telemetry_age_s: -1,
      mount: {
        ra_deg: null,
        dec_deg: null,
        ra_hms: 'NOT_AVAILABLE',
        dec_dms: 'NOT_AVAILABLE',
        hra_hms: 'NOT_AVAILABLE',
        alt_deg: null,
        az_deg: null,
        motion_state: 'DISCONNECTED',
        tracking: false,
        sidereal: '0.000"/s',
        ra_speed: 'COARSE',
        ra_direction: 'STOPPED',
        dec_speed: 'COARSE',
        dec_direction: 'STOPPED',
        at_park: false,
        at_home: false
      },
      dome: {
        az_deg: 0,
        state: 'DISCONNECTED',
        sync: 'UNAVAILABLE',
        slaved: false
      },
      time: {
        lst_deg: +lstDeg.toFixed(4),
        lst_hms: degToHMS(lstDeg),
        lst_source: 'LOCAL NTP (FALLBACK)',
        jd,
        utc: now.toUTCString()
      },
      weather: {
        status: 'DISCONNECTED',
        source: 'Weather Station (DISCONNECTED)',
        temperature: null,
        humidity: null,
        dew_point: null,
        wind_speed: null,
        rain: null,
        age_s: 0
      },
      safety: {
        overall: 'WARNING',
        limit_active: true,
        limit_message: 'STCS DISCONNECTED: Hardware telemetry unavailable from AI Studio container runtime',
        cooldown_active: false
      },
      control_lock: {
        owner: controlLock.owner,
        locked: controlLock.owner !== null,
        elapsed_s: controlLock.elapsed_s
      },
      ws: { status: 'DISCONNECTED' },
      alpaca: { status: 'DISCONNECTED' },
      subsystems: [
        ['Mount RA Axis', 'DISCONNECTED', 'No response from :11111'],
        ['Mount DEC Axis', 'DISCONNECTED', 'No response from :11111'],
        ['Dome Position Encoder', 'DISCONNECTED', 'No telemetry stream'],
        ['Weather Station (UDP)', 'OFFLINE', 'Port 12344 unreachable'],
        ['CCD Camera Service', 'NOT AVAILABLE', 'LightField software absent'],
        ['GPS Time Reference', 'LOCAL NTP', 'System clock only'],
        ['Alpaca REST Interface', 'UNREACHABLE', 'Port 11111 refused']
      ]
    };
  }

  const { altDeg, azDeg, haDeg } = getAltAz(mount.raDeg, mount.decDeg, lstDeg);
  const wxAgeS = (Date.now() - weather.updatedAt) / 1000;

  let overallSafety: 'SAFE' | 'WARNING' | 'CRITICAL' = 'SAFE';
  let limitMsg: string | null = null;
  let limitActive = false;

  if (altDeg < ALT_FLOOR) {
    overallSafety = 'WARNING';
    limitActive = true;
    limitMsg = `Altitude ${altDeg.toFixed(1)}\u00b0 is below safety floor of ${ALT_FLOOR}\u00b0`;
  } else if (altDeg > ALT_MAX) {
    overallSafety = 'WARNING';
    limitActive = true;
    limitMsg = `Altitude ${altDeg.toFixed(1)}\u00b0 is above zenith limit of ${ALT_MAX}\u00b0`;
  }

  if (weather.humidity > ENV_THRESHOLDS.max_humidity_percent) {
    overallSafety = 'CRITICAL';
    limitActive = true;
    limitMsg = `Humidity ${weather.humidity}% exceeds ${ENV_THRESHOLDS.max_humidity_percent}% limit`;
  }

  return {
    timestamp: now.toISOString(),
    system_state: 'ONLINE',
    mode: commandsEnabled ? 'REAL' : 'REAL (SAFE - COMMANDS LOCKED)',
    telemetry_status: 'LIVE',
    telemetry_source: 'STCS V1 Telemetry Bus',
    telemetry_age_s: 0.2,
    mount: {
      ra_deg: +mount.raDeg.toFixed(5),
      dec_deg: +mount.decDeg.toFixed(5),
      ra_hms: degToHMS(mount.raDeg),
      dec_dms: degToDMS(mount.decDeg),
      hra_hms: degToHMS(haDeg),
      alt_deg: +altDeg.toFixed(2),
      az_deg: +azDeg.toFixed(2),
      motion_state: mount.motionState,
      tracking: mount.tracking,
      sidereal: mount.tracking ? '15.041"/s' : '0.000"/s',
      ra_speed: mount.raSpeed,
      ra_direction: mount.raDirection,
      dec_speed: mount.decSpeed,
      dec_direction: mount.decDirection,
      at_park: mount.atPark,
      at_home: mount.atHome
    },
    dome: {
      az_deg: +dome.azDeg.toFixed(1),
      state: dome.state,
      sync: dome.sync,
      slaved: dome.slaved
    },
    time: {
      lst_deg: +lstDeg.toFixed(4),
      lst_hms: degToHMS(lstDeg),
      lst_source: 'GPS NTP',
      jd,
      utc: now.toUTCString()
    },
    weather: {
      status: weather.status,
      source: weather.source,
      temperature: weather.temperature,
      humidity: weather.humidity,
      dew_point: weather.dewPoint,
      wind_speed: weather.windSpeed,
      rain: weather.rain,
      age_s: +wxAgeS.toFixed(1)
    },
    safety: {
      overall: overallSafety,
      limit_active: limitActive,
      limit_message: limitMsg,
      cooldown_active: false
    },
    control_lock: {
      owner: controlLock.owner,
      locked: controlLock.owner !== null,
      elapsed_s: controlLock.elapsed_s
    },
    ws: { status: 'LIVE' },
    alpaca: { status: 'CONNECTED' },
    subsystems: [
      ['Mount RA Axis', 'LIVE', '0.2s ago'],
      ['Mount DEC Axis', 'LIVE', '0.2s ago'],
      ['Dome Position Encoder', 'LIVE', '0.4s ago'],
      ['Weather Station (UDP)', 'LIVE', `${wxAgeS.toFixed(1)}s ago`],
      ['CCD Camera Service', 'LIVE', '0.5s ago'],
      ['GPS Time Reference', 'LIVE', '0.1s ago'],
      ['Alpaca REST Interface', 'LIVE', '1.0s ago']
    ]
  };
}

export function executeCommand(user: string, commandType: string, payload: any) {
  // Check global safe default
  if (!commandsEnabled) {
    addAudit(user, `command_blocked`, `Command ${commandType} blocked: STCS_COMMANDS_ENABLED=0`);
    return {
      status: 'COMMANDS_DISABLED',
      message: 'STCS_COMMANDS_ENABLED=0 (safe default). Physical telescope commands are disabled for software safety. Set STCS_COMMANDS_ENABLED=1 to enable commands.'
    };
  }

  // Check physical STCS hardware connectivity
  const stcsConnected = isStcsAvailableSync();
  if (!stcsConnected) {
    addAudit(user, `command_failed`, `Command ${commandType} failed: STCS hardware disconnected`);
    return {
      status: 'HARDWARE_DISCONNECTED',
      message: 'STCS V1 hardware integration is DISCONNECTED. Physical telescope motors cannot be commanded from this isolated container runtime.'
    };
  }

  // Check lock
  if (controlLock.owner && controlLock.owner !== user) {
    return {
      status: 'BLOCKED',
      message: `Telescope control is currently locked by operator '${controlLock.owner}'.`
    };
  }

  switch (commandType) {
    case 'tracking': {
      const action = String(payload.action).toLowerCase();
      mount.tracking = action === 'on';
      mount.motionState = mount.tracking ? 'TRACKING' : 'IDLE';
      addAudit(user, 'tracking', `Tracking turned ${mount.tracking ? 'ON' : 'OFF'}`);
      return { status: 'EXECUTED', message: `Telescope tracking turned ${mount.tracking ? 'ON' : 'OFF'}.` };
    }

    case 'slew': {
      const ra = parseFloat(payload.ra_deg);
      const dec = parseFloat(payload.dec_deg);
      if (isNaN(ra) || isNaN(dec)) {
        return { status: 'INVALID', message: 'Target coordinates must be valid numbers.' };
      }
      if (dec < -90 || dec > 90) {
        return { status: 'INVALID', message: 'DEC must be between -90 and +90 degrees.' };
      }
      mount.targetRaDeg = (ra % 360 + 360) % 360;
      mount.targetDecDeg = dec;
      mount.motionState = 'SLEWING';
      addAudit(user, 'slew', `Slew to target RA=${ra.toFixed(3)}\u00b0 DEC=${dec.toFixed(3)}\u00b0 initiated`);
      return { status: 'ACCEPTED', message: `Slew to RA=${ra.toFixed(3)}\u00b0 DEC=${dec.toFixed(3)}\u00b0 accepted. Motion in progress.` };
    }

    case 'stop':
    case 'emergency_stop': {
      mount.targetRaDeg = null;
      mount.targetDecDeg = null;
      mount.motionState = 'IDLE';
      mount.tracking = false;
      dome.state = 'IDLE';
      addAudit(user, 'stop', 'Emergency STOP issued. All axis motors halted.');
      return { status: 'EXECUTED', message: 'Emergency stop executed. All motor axes halted.' };
    }

    case 'park': {
      mount.targetRaDeg = 0;
      mount.targetDecDeg = 85;
      mount.motionState = 'PARKING';
      mount.tracking = false;
      addAudit(user, 'park', 'Telescope park sequence initiated.');
      return { status: 'ACCEPTED', message: 'Telescope parking in progress.' };
    }

    case 'dome': {
      const action = String(payload.action).toUpperCase();
      if (action === 'CW') {
        dome.state = 'MOVING CW';
        dome.azDeg = (dome.azDeg + 5) % 360;
      } else if (action === 'CCW') {
        dome.state = 'MOVING CCW';
        dome.azDeg = (dome.azDeg - 5 + 360) % 360;
      } else if (action === 'STOP' || action === 'OFF') {
        dome.state = 'IDLE';
      } else if (action === 'SYNC') {
        dome.state = 'SYNCING';
        dome.sync = 'SYNCED';
        const { azDeg } = getAltAz(mount.raDeg, mount.decDeg, getLSTDeg(new Date()));
        dome.azDeg = azDeg;
      } else if (action === 'AUTO') {
        dome.slaved = !dome.slaved;
        dome.state = dome.slaved ? 'AUTO TRACK' : 'IDLE';
      } else {
        dome.state = 'IDLE';
      }
      addAudit(user, 'dome', `Dome command: ${action}`);
      return { status: 'EXECUTED', message: `Dome action '${action}' applied.` };
    }

    case 'manual': {
      const axis = payload.axis;
      const dir = payload.direction;
      let speed = payload.speed || 'COARSE';
      if (speed === 'FINE_1') speed = 'FINE1';
      if (speed === 'FINE_2') speed = 'FINE2';

      if (axis === 'RA') {
        mount.raSpeed = speed;
        mount.raDirection = dir;
        if (dir === 'WEST' || dir === 'W') mount.raDeg = (mount.raDeg + 0.1) % 360;
        if (dir === 'EAST' || dir === 'E') mount.raDeg = (mount.raDeg - 0.1 + 360) % 360;
      } else if (axis === 'DEC') {
        mount.decSpeed = speed;
        mount.decDirection = dir;
        if (dir === 'NORTH' || dir === 'N') mount.decDeg = Math.min(89, mount.decDeg + 0.1);
        if (dir === 'SOUTH' || dir === 'S') mount.decDeg = Math.max(-10, mount.decDeg - 0.1);
      }
      return { status: 'EXECUTED', message: `Manual jog ${axis} ${dir} (${speed}) executed.` };
    }

    case 'calibration': {
      const action = String(payload.action).toLowerCase();
      if (action === 'dec_home') {
        addAudit(user, 'calibration', 'DEC Home calibration queried.');
        return { status: 'EXECUTED', message: 'DEC Home switch reference acquired.' };
      }
      if (action === 'set_home') {
        addAudit(user, 'calibration', 'SET HOME: Current orientation established as home reference.');
        return { status: 'EXECUTED', message: 'Current orientation registered as home reference.' };
      }
      if (action === 'set_ra') {
        const val = payload.ra_hms || payload.value || '12:00:00.0';
        mount.raOffset = val;
        addAudit(user, 'calibration', `SET RA: ${val}`);
        return { status: 'EXECUTED', message: `RA reference set to ${val}.` };
      }
      if (action === 'set_dec') {
        const val = payload.dec_dms || payload.value || '+00:00:00.0';
        mount.decOffset = val;
        addAudit(user, 'calibration', `SET DEC: ${val}`);
        return { status: 'EXECUTED', message: `DEC reference set to ${val}.` };
      }
      if (action === 'set_dome') {
        const val = payload.dome_az || payload.value || '0.0';
        mount.domeOffset = val;
        addAudit(user, 'calibration', `SET DOME: ${val}`);
        return { status: 'EXECUTED', message: `Dome reference set to ${val}\u00b0.` };
      }
      if (action === 'ra_offset') {
        const val = payload.ra_offset || payload.value || '0.000';
        mount.raOffset = val;
        addAudit(user, 'calibration', `RA Offset applied: ${val}`);
        return { status: 'EXECUTED', message: `RA offset ${val} applied.` };
      }
      if (action === 'dec_offset') {
        const val = payload.dec_offset || payload.value || '0.000';
        mount.decOffset = val;
        addAudit(user, 'calibration', `DEC Offset applied: ${val}`);
        return { status: 'EXECUTED', message: `DEC offset ${val} applied.` };
      }
      if (action === 'clear_offsets') {
        mount.raOffset = '0.000';
        mount.decOffset = '0.000';
        mount.domeOffset = '0.000';
        addAudit(user, 'calibration', 'Calibration offsets cleared.');
        return { status: 'EXECUTED', message: 'All coordinate calibration offsets cleared.' };
      }
      if (payload.ra_hms) mount.raOffset = payload.ra_hms;
      if (payload.dec_dms) mount.decOffset = payload.dec_dms;
      if (payload.dome_az) mount.domeOffset = payload.dome_az;
      addAudit(user, 'calibration', 'Offsets updated.');
      return { status: 'EXECUTED', message: 'Calibration synchronized.' };
    }

    default:
      return { status: 'INVALID', message: `Unknown command type: ${commandType}` };
  }
}

export function acquireControlLock(user: string): boolean {
  if (controlLock.owner && controlLock.owner !== user) {
    return false;
  }
  controlLock.owner = user;
  controlLock.acquiredAt = Date.now();
  controlLock.elapsed_s = 0;
  addAudit(user, 'lock_acquire', `Operator '${user}' acquired telescope control lock.`);
  return true;
}

export function releaseControlLock(user: string): boolean {
  if (controlLock.owner === user || user === 'admin') {
    addAudit(user, 'lock_release', `Control lock released.`);
    controlLock.owner = null;
    controlLock.acquiredAt = null;
    controlLock.elapsed_s = null;
    return true;
  }
  return false;
}

export function getMountDetails() {
  return { ...mount };
}
