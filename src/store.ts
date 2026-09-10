import crypto from 'crypto';
import { ObservationRecord, ObservationFile, AuditEvent } from './types.js';

const observations: ObservationRecord[] = [
  {
    id: 101,
    target: 'M42 Orion Nebula',
    ra_deg: 83.822,
    dec_deg: -5.391,
    start: new Date(Date.now() - 4 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    end: new Date(Date.now() - 3.8 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    duration_s: 720,
    status: 'completed',
    owner: 'scientist',
    notes: 'Spectroscopic run in H-alpha line. Excellent seeing ~1.2 arcsec.',
    telescope_state: {
      ra_hms: '05:35:17.2',
      dec_dms: '-05:23:28',
      alt_deg: 54.2,
      az_deg: 172.5,
      weather: {
        temperature: 9.4,
        humidity: 62.0,
        wind_speed: 12.5,
        rain: false
      }
    },
    files: [
      {
        id: 1,
        filename: 'M42_Halpha_720s_001.spe',
        kind: 'raw_spe',
        file_size: 4194304,
        checksum: crypto.createHash('sha256').update('M42_raw_frame_1').digest('hex'),
        created_at: new Date(Date.now() - 3.8 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
        buffer: Buffer.from('SIMULATED_SPE_DATA_HEADER_BINARY_BLOCK_FOR_M42')
      }
    ]
  },
  {
    id: 102,
    target: 'NGC 7331 Spiral Galaxy',
    ra_deg: 339.267,
    dec_deg: 34.416,
    start: new Date(Date.now() - 26 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    end: new Date(Date.now() - 25.5 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    duration_s: 1800,
    status: 'completed',
    owner: 'scientist',
    notes: 'Deep field exposure with medium gain and 2 MHz readout mode.',
    telescope_state: {
      ra_hms: '22:37:04.1',
      dec_dms: '+34:24:58',
      alt_deg: 68.1,
      az_deg: 215.3,
      weather: {
        temperature: 8.1,
        humidity: 58.4,
        wind_speed: 14.1,
        rain: false
      }
    },
    files: [
      {
        id: 2,
        filename: 'NGC7331_Bband_1800s_001.spe',
        kind: 'raw_spe',
        file_size: 8388608,
        checksum: crypto.createHash('sha256').update('NGC7331_raw_frame_1').digest('hex'),
        created_at: new Date(Date.now() - 25.5 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
        buffer: Buffer.from('SIMULATED_SPE_DATA_HEADER_BINARY_BLOCK_FOR_NGC7331')
      }
    ]
  },
  {
    id: 103,
    target: 'M1 Crab Nebula',
    ra_deg: 83.633,
    dec_deg: 22.014,
    start: new Date(Date.now() - 50 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    end: new Date(Date.now() - 49.8 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
    duration_s: 600,
    status: 'completed',
    owner: 'operator',
    notes: 'Standard photometric reference calibration test.',
    telescope_state: {
      ra_hms: '05:34:31.9',
      dec_dms: '+22:00:52',
      alt_deg: 45.8,
      az_deg: 140.2,
      weather: {
        temperature: 11.2,
        humidity: 64.1,
        wind_speed: 9.8,
        rain: false
      }
    },
    files: [
      {
        id: 3,
        filename: 'M1_Cal_600s_001.spe',
        kind: 'raw_spe',
        file_size: 4194304,
        checksum: crypto.createHash('sha256').update('M1_raw_cal_frame').digest('hex'),
        created_at: new Date(Date.now() - 49.8 * 3600000).toISOString().replace('T', ' ').slice(0, 19),
        buffer: Buffer.from('SIMULATED_SPE_DATA_HEADER_BINARY_BLOCK_FOR_M1')
      }
    ]
  }
];

let nextObsId = 104;
let nextFileId = 4;

const auditLog: AuditEvent[] = [
  {
    user: 'system',
    action: 'startup',
    detail: 'STCS Web Server initialized at Manora Peak (safe commands mode)',
    timestamp: new Date(Date.now() - 3600000).toISOString().replace('T', ' ').slice(0, 19)
  },
  {
    user: 'operator',
    action: 'login',
    detail: 'Operator session authenticated from console',
    timestamp: new Date(Date.now() - 1800000).toISOString().replace('T', ' ').slice(0, 19)
  }
];

export function addAudit(user: string, action: string, detail: string) {
  auditLog.unshift({
    user,
    action,
    detail,
    timestamp: new Date().toISOString().replace('T', ' ').slice(0, 19)
  });
  if (auditLog.length > 200) auditLog.pop();
}

export function getAudit(): [string, string, string, string][] {
  return auditLog.map(a => [a.user, a.action, a.detail, a.timestamp]);
}

export function getAllObservations(filter?: {
  q?: string;
  status?: string;
  from?: string;
  to?: string;
  owner?: string;
}): ObservationRecord[] {
  let list = [...observations];
  if (filter?.q) {
    const q = filter.q.toLowerCase();
    list = list.filter(o => o.target.toLowerCase().includes(q) || o.notes.toLowerCase().includes(q));
  }
  if (filter?.status) {
    list = list.filter(o => o.status === filter.status);
  }
  if (filter?.owner) {
    list = list.filter(o => o.owner.toLowerCase() === filter.owner!.toLowerCase());
  }
  if (filter?.from) {
    list = list.filter(o => o.start >= filter.from!);
  }
  if (filter?.to) {
    list = list.filter(o => o.start <= filter.to! + ' 23:59:59');
  }
  list.sort((a, b) => (b.start > a.start ? 1 : -1));
  return list;
}

export function getObservationById(id: number): ObservationRecord | undefined {
  return observations.find(o => o.id === id);
}

export function addObservation(obs: Omit<ObservationRecord, 'id'>): ObservationRecord {
  const newRec: ObservationRecord = {
    ...obs,
    id: nextObsId++
  };
  observations.unshift(newRec);
  return newRec;
}

export function deleteObservation(id: number): boolean {
  const idx = observations.findIndex(o => o.id === id);
  if (idx === -1) return false;
  observations.splice(idx, 1);
  return true;
}

export function getObservationsSummary() {
  const total = observations.length;
  const totalSecs = observations.reduce((acc, o) => acc + (o.duration_s || 0), 0);
  const hours = (totalSecs / 3600).toFixed(1);
  const targets = new Set(observations.map(o => o.target)).size;
  const latest = observations.length ? observations[0].target : 'None';
  return { total, hours, targets, latest };
}

export function getScientistStats() {
  const statsMap: Record<string, { count: number; last: string }> = {};
  for (const o of observations) {
    if (!statsMap[o.owner]) {
      statsMap[o.owner] = { count: 0, last: o.start };
    }
    statsMap[o.owner].count++;
    if (o.start > statsMap[o.owner].last) {
      statsMap[o.owner].last = o.start;
    }
  }
  return Object.entries(statsMap).map(([username, data]) => ({
    username,
    observation_count: data.count,
    last_observation: data.last
  }));
}

export function addFileToObservation(obsId: number, fileData: {
  filename: string;
  kind: string;
  buffer: Buffer;
}): ObservationFile {
  const obs = getObservationById(obsId);
  const file: ObservationFile = {
    id: nextFileId++,
    filename: fileData.filename,
    kind: fileData.kind,
    file_size: fileData.buffer.length,
    checksum: crypto.createHash('sha256').update(fileData.buffer).digest('hex'),
    created_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
    buffer: fileData.buffer
  };
  if (obs) {
    obs.files = obs.files || [];
    obs.files.push(file);
  }
  return file;
}

export function getFileById(fileId: number): ObservationFile | undefined {
  for (const o of observations) {
    if (o.files) {
      const found = o.files.find(f => f.id === fileId);
      if (found) return found;
    }
  }
  return undefined;
}
