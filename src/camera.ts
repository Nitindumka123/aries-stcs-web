import crypto from 'crypto';
import { addObservation, addFileToObservation, addAudit } from './store.js';
import { getTelemetrySnapshot } from './observatory.js';

interface CameraState {
  connected: boolean;
  driver_available: boolean;
  mock_mode: boolean;
  temperature: number;
  state: 'READY' | 'CONNECTED' | 'EXPOSING' | 'READING' | 'SAVING' | 'NOT_AVAILABLE';
  exposing: boolean;
  lock: {
    locked: boolean;
    owner: string | null;
    start_time: number | null;
    elapsed_s: number | null;
  };
}

const cameraState: CameraState = {
  connected: true,
  driver_available: true,
  mock_mode: true,
  temperature: -65.0,
  state: 'READY',
  exposing: false,
  lock: {
    locked: false,
    owner: null,
    start_time: null,
    elapsed_s: null
  }
};

let abortSignal = false;

export function getCameraStatus() {
  if (cameraState.lock.locked && cameraState.lock.start_time) {
    cameraState.lock.elapsed_s = (Date.now() - cameraState.lock.start_time) / 1000;
  }
  return {
    connected: cameraState.connected,
    driver_available: cameraState.driver_available,
    mock_mode: cameraState.mock_mode,
    temperature: cameraState.temperature,
    state: cameraState.state,
    exposing: cameraState.exposing,
    acquisition_lock: {
      locked: cameraState.lock.locked,
      owner: cameraState.lock.owner,
      elapsed_s: cameraState.lock.elapsed_s
    }
  };
}

export function connectCamera(user: string) {
  cameraState.connected = true;
  cameraState.state = 'READY';
  addAudit(user, 'camera_connect', 'CCD camera interface connected (simulation mode)');
  return { success: true, mock_mode: true };
}

export function disconnectCamera(user: string) {
  if (cameraState.exposing) {
    return { success: false, error: 'Cannot disconnect while exposure is in progress.' };
  }
  cameraState.connected = false;
  cameraState.state = 'NOT_AVAILABLE';
  addAudit(user, 'camera_disconnect', 'CCD camera disconnected');
  return { success: true };
}

export async function acquireFrame(user: string, params: {
  target: string;
  exposure: number;
  binning?: number[];
  gain?: string;
  shutter?: string;
  adc_speed?: string;
  readout_mode?: string;
  notes?: string;
}) {
  if (!cameraState.connected) {
    return { success: false, error: 'Camera is not connected.' };
  }
  if (cameraState.lock.locked) {
    return { success: false, error: `Camera is locked by ${cameraState.lock.owner}` };
  }

  cameraState.lock.locked = true;
  cameraState.lock.owner = user;
  cameraState.lock.start_time = Date.now();
  cameraState.lock.elapsed_s = 0;
  cameraState.exposing = true;
  cameraState.state = 'EXPOSING';
  abortSignal = false;

  const target = params.target || 'untitled';
  const exposureTimeS = Math.max(0.1, params.exposure || 1.0);
  const snap = getTelemetrySnapshot();

  addAudit(user, 'exposure_start', `Target: ${target}, Exposure: ${exposureTimeS}s`);

  // Simulate exposure duration (capped at 3 seconds for responsive web preview if exposure is long)
  const simDurationMs = Math.min(exposureTimeS * 1000, 2500);
  await new Promise(resolve => setTimeout(resolve, simDurationMs));

  if (abortSignal) {
    cameraState.exposing = false;
    cameraState.state = 'READY';
    cameraState.lock.locked = false;
    cameraState.lock.owner = null;
    return { success: false, error: 'Acquisition aborted by operator.' };
  }

  cameraState.state = 'SAVING';

  // Generate mock SPE binary data
  const binW = (params.binning && params.binning[0]) || 1;
  const binH = (params.binning && params.binning[1]) || 1;
  const width = Math.floor(2048 / binW);
  const height = Math.floor(2048 / binH);
  const totalPixels = width * height;
  const buffer = Buffer.alloc(4100 + totalPixels * 2);

  // Write SPE header signature
  buffer.write('SPE_V3.0_HEADER', 0, 'ascii');
  buffer.writeUInt16LE(width, 42);
  buffer.writeUInt16LE(height, 656);

  const cleanTarget = target.replace(/[^a-zA-Z0-9_-]/g, '_');
  const filename = `${cleanTarget}_${exposureTimeS}s_${Date.now().toString().slice(-6)}.spe`;
  const checksum = crypto.createHash('sha256').update(buffer).digest('hex');

  const obs = addObservation({
    target,
    ra_deg: snap.mount.ra_deg,
    dec_deg: snap.mount.dec_deg,
    start: new Date(cameraState.lock.start_time!).toISOString().replace('T', ' ').slice(0, 19),
    end: new Date().toISOString().replace('T', ' ').slice(0, 19),
    duration_s: exposureTimeS,
    status: 'completed',
    owner: user,
    notes: params.notes || `Acquired with gain=${params.gain || 'medium'}, binning=${binW}x${binH}, shutter=${params.shutter || 'normal'}`,
    telescope_state: {
      ra_hms: snap.mount.ra_hms,
      dec_dms: snap.mount.dec_dms,
      alt_deg: snap.mount.alt_deg,
      az_deg: snap.mount.az_deg,
      weather: {
        temperature: snap.weather.temperature,
        humidity: snap.weather.humidity,
        wind_speed: snap.weather.wind_speed,
        rain: snap.weather.rain
      }
    }
  });

  const file = addFileToObservation(obs.id, {
    filename,
    kind: 'raw_spe',
    buffer
  });

  cameraState.exposing = false;
  cameraState.state = 'READY';
  cameraState.lock.locked = false;
  cameraState.lock.owner = null;

  addAudit(user, 'exposure_complete', `Saved ${filename} (${(buffer.length / 1048576).toFixed(1)} MB) to observation #${obs.id}`);

  return {
    success: true,
    obs_id: obs.id,
    file_id: file.id,
    filename,
    file_size: buffer.length,
    checksum,
    elapsed_s: exposureTimeS
  };
}

export function abortAcquisition(user: string) {
  if (!cameraState.exposing && !cameraState.lock.locked) {
    return { success: false, error: 'No active exposure to abort.' };
  }
  abortSignal = true;
  cameraState.exposing = false;
  cameraState.state = 'READY';
  cameraState.lock.locked = false;
  cameraState.lock.owner = null;
  addAudit(user, 'exposure_abort', 'Exposure aborted by operator');
  return { success: true };
}
