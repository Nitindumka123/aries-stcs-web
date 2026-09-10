import net from 'net';

export interface DependencyProbe {
  name: string;
  configured: string;
  available: boolean;
  error?: string;
  lastChecked: number;
}

export interface RuntimeDiagnostics {
  environment: {
    platform: string;
    runtime: string;
    nodeVersion: string;
    containerHostname: string;
    cwd: string;
    isCloudRun: boolean;
    isLocalObservatory: boolean;
    envLoadedFrom: string;
  };
  dependencies: {
    postgres: {
      available: boolean;
      host: string;
      port: number;
      database: string;
      user: string;
      error?: string;
    };
    stcs: {
      available: boolean;
      alpacaHost: string;
      alpacaPort: number;
      telemetryWsHost: string;
      telemetryWsPort: number;
      commandsEnabled: boolean;
      error?: string;
    };
    camera: {
      available: boolean;
      hardwareDriver: string;
      reason: string;
    };
    weather: {
      available: boolean;
      port: number;
      error?: string;
    };
    authStore: {
      type: 'POSTGRESQL' | 'DEVELOPMENT_FALLBACK';
      databaseAvailable: boolean;
      activeStoreDescription: string;
    };
  };
  overallStatus: 'RUNTIME NOT CONNECTED' | 'RUNTIME PARTIALLY CONNECTED' | 'RUNTIME CONNECTED';
}

// Cached states with 3-second TTL
let cachedDiagnostics: RuntimeDiagnostics | null = null;
let lastCheckTime = 0;
const CACHE_TTL_MS = 3000;

function probeTcpPort(host: string, port: number, timeoutMs = 400): Promise<{ connected: boolean; error?: string }> {
  return new Promise((resolve) => {
    // Normalizing 0.0.0.0 for client connect
    const targetHost = (host === '0.0.0.0' || host === '') ? '127.0.0.1' : host;
    const socket = new net.Socket();
    let settled = false;

    socket.setTimeout(timeoutMs);

    socket.on('connect', () => {
      if (!settled) {
        settled = true;
        socket.destroy();
        resolve({ connected: true });
      }
    });

    socket.on('error', (err) => {
      if (!settled) {
        settled = true;
        socket.destroy();
        resolve({ connected: false, error: err.message });
      }
    });

    socket.on('timeout', () => {
      if (!settled) {
        settled = true;
        socket.destroy();
        resolve({ connected: false, error: 'Connection timed out' });
      }
    });

    try {
      socket.connect(port, targetHost);
    } catch (e: any) {
      if (!settled) {
        settled = true;
        resolve({ connected: false, error: e?.message || 'Socket error' });
      }
    }
  });
}

export async function runRuntimeDiagnostics(forceRefresh = false): Promise<RuntimeDiagnostics> {
  const now = Date.now();
  if (!forceRefresh && cachedDiagnostics && (now - lastCheckTime < CACHE_TTL_MS)) {
    return cachedDiagnostics;
  }

  const dbHost = process.env.DB_HOST || 'localhost';
  const dbPort = parseInt(process.env.DB_PORT || '5432', 10);
  const dbName = process.env.DB_NAME || 'stcs_observatory';
  const dbUser = process.env.DB_USER || 'stcs_user';

  const alpacaHost = process.env.ALPACA_HOST || '0.0.0.0';
  const alpacaPort = parseInt(process.env.ALPACA_PORT || '11111', 10);

  const wsHost = process.env.TELEMETRY_WS_HOST || '0.0.0.0';
  const wsPort = parseInt(process.env.TELEMETRY_WS_PORT || '11112', 10);

  const weatherPort = parseInt(process.env.WEATHER_PORT || '12344', 10);

  const [pgCheck, alpacaCheck, wsCheck, weatherCheck] = await Promise.all([
    probeTcpPort(dbHost, dbPort),
    probeTcpPort(alpacaHost, alpacaPort),
    probeTcpPort(wsHost, wsPort),
    probeTcpPort('127.0.0.1', weatherPort)
  ]);

  const isCloudRun = Boolean(process.env.K_SERVICE || process.env.GOOGLE_RUNTIME);
  const isLocalObservatory = !isCloudRun && (pgCheck.connected || alpacaCheck.connected);

  const stcsAvailable = alpacaCheck.connected || wsCheck.connected;
  const pgAvailable = pgCheck.connected;
  const cameraAvailable = false; // LightField Windows COM automation unavailable on Linux container

  let overallStatus: 'RUNTIME NOT CONNECTED' | 'RUNTIME PARTIALLY CONNECTED' | 'RUNTIME CONNECTED' = 'RUNTIME NOT CONNECTED';
  if (pgAvailable && stcsAvailable && cameraAvailable) {
    overallStatus = 'RUNTIME CONNECTED';
  } else if (pgAvailable || stcsAvailable || cameraAvailable) {
    overallStatus = 'RUNTIME PARTIALLY CONNECTED';
  } else {
    overallStatus = 'RUNTIME NOT CONNECTED';
  }

  const authStoreType: 'POSTGRESQL' | 'DEVELOPMENT_FALLBACK' = pgAvailable ? 'POSTGRESQL' : 'DEVELOPMENT_FALLBACK';

  cachedDiagnostics = {
    environment: {
      platform: process.platform,
      runtime: `Node.js ${process.version}`,
      nodeVersion: process.version,
      containerHostname: process.env.HOSTNAME || 'container-host',
      cwd: process.cwd(),
      isCloudRun,
      isLocalObservatory,
      envLoadedFrom: 'Container Environment (Cloud Run injection)'
    },
    dependencies: {
      postgres: {
        available: pgAvailable,
        host: dbHost,
        port: dbPort,
        database: dbName,
        user: dbUser,
        error: pgCheck.error
      },
      stcs: {
        available: stcsAvailable,
        alpacaHost,
        alpacaPort,
        telemetryWsHost: wsHost,
        telemetryWsPort: wsPort,
        commandsEnabled: process.env.STCS_COMMANDS_ENABLED === '1',
        error: !stcsAvailable ? (alpacaCheck.error || wsCheck.error || 'STCS V1 server unreachable') : undefined
      },
      camera: {
        available: false,
        hardwareDriver: 'Princeton Instruments LightField (Windows COM)',
        reason: 'LightField Windows automation unavailable in Linux container runtime'
      },
      weather: {
        available: weatherCheck.connected,
        port: weatherPort,
        error: weatherCheck.error
      },
      authStore: {
        type: authStoreType,
        databaseAvailable: pgAvailable,
        activeStoreDescription: pgAvailable
          ? `PostgreSQL (${dbHost}:${dbPort}/${dbName})`
          : 'In-Memory Development Fallback Store (PostgreSQL is unavailable)'
      }
    },
    overallStatus
  };

  lastCheckTime = now;
  return cachedDiagnostics;
}

export function isPostgresAvailableSync(): boolean {
  if (cachedDiagnostics) {
    return cachedDiagnostics.dependencies.postgres.available;
  }
  return false;
}

export function isStcsAvailableSync(): boolean {
  if (cachedDiagnostics) {
    return cachedDiagnostics.dependencies.stcs.available;
  }
  return false;
}
