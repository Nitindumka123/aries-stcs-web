export interface User {
  id: number;
  username: string;
  passwordHash: string;
  role: 'admin' | 'operator' | 'scientist' | 'engineer';
  approved: boolean;
  createdAt: string;
}

export interface WeatherData {
  status: 'LIVE' | 'STALE' | 'OFFLINE';
  source: string;
  temperature: number;
  humidity: number;
  dewPoint: number;
  windSpeed: number;
  rain: boolean;
  updatedAt: number;
}

export interface ControlLock {
  owner: string | null;
  acquiredAt: number | null;
  elapsed_s: number | null;
}

export interface TelemetrySnapshot {
  timestamp: string;
  system_state: string;
  mode: string;
  telemetry_status: 'LIVE' | 'STALE' | 'DOWN' | 'DISCONNECTED';
  telemetry_source: string;
  telemetry_age_s: number;
  mount: {
    ra_deg: number | null;
    dec_deg: number | null;
    ra_hms: string;
    dec_dms: string;
    hra_hms: string;
    alt_deg: number | null;
    az_deg: number | null;
    motion_state: 'IDLE' | 'SLEWING' | 'TRACKING' | 'PARKING' | 'DISCONNECTED';
    tracking: boolean;
    sidereal: string;
    ra_speed: string;
    ra_direction: string;
    dec_speed: string;
    dec_direction: string;
    at_park: boolean;
    at_home: boolean;
  };
  dome: {
    az_deg: number;
    state: string;
    sync: string;
    slaved: boolean;
  };
  time: {
    lst_deg: number;
    lst_hms: string;
    lst_source: string;
    jd: string;
    utc: string;
  };
  weather: {
    status: string;
    source: string;
    temperature: number | null;
    humidity: number | null;
    dew_point: number | null;
    wind_speed: number | null;
    rain: boolean | null;
    age_s: number;
  };
  safety: {
    overall: 'SAFE' | 'WARNING' | 'CRITICAL' | 'UNKNOWN';
    limit_active: boolean;
    limit_message: string | null;
    cooldown_active: boolean;
  };
  control_lock: {
    owner: string | null;
    locked: boolean;
    elapsed_s: number | null;
  };
  ws: {
    status: 'LIVE' | 'STALE' | 'DOWN' | 'DISCONNECTED';
  };
  alpaca: {
    status: 'CONNECTED' | 'DISCONNECTED';
  };
  subsystems: [string, string, string][];
}

export interface ObservationFile {
  id: number;
  filename: string;
  kind: string;
  file_size: number;
  checksum: string;
  created_at: string;
  buffer?: Buffer;
}

export interface ObservationRecord {
  id: number;
  target: string;
  ra_deg: number;
  dec_deg: number;
  start: string;
  end: string;
  duration_s: number;
  status: 'completed' | 'in_progress' | 'failed' | 'aborted';
  owner: string;
  notes: string;
  telescope_state?: any;
  files?: ObservationFile[];
}

export interface AuditEvent {
  user: string;
  action: string;
  detail: string;
  timestamp: string;
}
