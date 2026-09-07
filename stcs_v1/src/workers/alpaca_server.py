# src/workers/alpaca_server.py
"""
ASCOM Alpaca Telescope Server for Cartes du Ciel 4.2.1 on Windows.

Implements the ASCOM Alpaca REST API over HTTP. This is far more reliable
than INDI on Windows since it's standard HTTP - no socket/XML quirks.

Endpoints:
  Management API:
    GET  /management/apiversions         → [1]
    GET  /management/v1/description      → server info
    GET  /management/v1/configureddevices → device list

  Telescope Device API (device 0):
    GET  /api/v1/telescope/0/<property>  → get property
    PUT  /api/v1/telescope/0/<method>    → execute method

  UDP Discovery on port 32227:
    Responds to "alpacadiscovery1" with {"AlpacaPort": <port>}

Default port: 11111 (configurable via ALPACA_PORT env var)
"""
import os
import json
import socket
import threading
import time
import logging
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("AlpacaServer")

# Server metadata
SERVER_NAME = "ARIES STCS Alpaca Server"
MANUFACTURER = "ARIES Nainital"
SERVER_VERSION = "1.0.0"
DEVICE_NAME = "ARIES 104CM Telescope"

# Shared state - set by AlpacaServerThread before starting
_motion_state = None
_slew_engine = None
_astro = None
_cached_coords = {
    'ra_h': 0.0,
    'dec_d': 0.0,
    'lst_h': 0.0,
    'alt_deg': 0.0,
    'az_deg': 0.0,
}

# Transaction tracking
_server_transaction_id = 0


def _next_server_tid():
    global _server_transaction_id
    _server_transaction_id += 1
    return _server_transaction_id


class AlpacaRequestHandler(BaseHTTPRequestHandler):
    """Handles ASCOM Alpaca HTTP requests."""

    def address_string(self):
        """Override to prevent slow reverse DNS lookups that cause 2-second delays."""
        host, port = self.client_address[:2]
        return host

    def log_message(self, format, *args):
        """Route HTTP server logs through our logger."""
        logger.debug(f"HTTP: {args[0]}")

    # ═══════════════════════════════════════════════════════════
    # GET handler
    # ═══════════════════════════════════════════════════════════
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/').lower()
        params = parse_qs(parsed.query)

        # Extract ClientID and ClientTransactionID
        lower_params = {k.lower(): v for k, v in params.items()}
        client_tid = int(lower_params.get('clienttransactionid', [0])[0])

        # ── Management API ──
        if path == '/management/apiversions':
            return self._json_response({"Value": [1]}, client_tid)

        elif path == '/management/v1/description':
            return self._json_response({
                "Value": {
                    "ServerName": SERVER_NAME,
                    "Manufacturer": MANUFACTURER,
                    "ManufacturerVersion": SERVER_VERSION,
                    "Location": "ARIES, Nainital, India"
                }
            }, client_tid)

        elif path == '/management/v1/configureddevices':
            return self._json_response({
                "Value": [{
                    "DeviceName": DEVICE_NAME,
                    "DeviceType": "Telescope",
                    "DeviceNumber": 0,
                    "UniqueID": "aries-104cm-stcs-v1"
                }]
            }, client_tid)

        # ── Telescope Device API ──
        elif path.startswith('/api/v1/telescope/0/'):
            prop = path.split('/')[-1]
            return self._handle_telescope_get(prop, client_tid)

        else:
            self._error_response(400, f"Unknown endpoint: {path}", client_tid)

    # ═══════════════════════════════════════════════════════════
    # PUT handler
    # ═══════════════════════════════════════════════════════════
    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/').lower()

        # Read body
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else ""
        params = parse_qs(body)

        # Flatten single-value params
        flat = {}
        for k, v in params.items():
            flat[k.lower()] = v[0] if len(v) == 1 else v

        client_tid = int(flat.get('clienttransactionid', 0))

        if path.startswith('/api/v1/telescope/0/'):
            method = path.split('/')[-1]
            return self._handle_telescope_put(method, flat, client_tid)
        else:
            self._error_response(400, f"Unknown endpoint: {path}", client_tid)

    # ═══════════════════════════════════════════════════════════
    # TELESCOPE GET properties
    # ═══════════════════════════════════════════════════════════
    def _handle_telescope_get(self, prop, client_tid):
        ms = _motion_state
        prop_lower = prop.lower()
        
        # Pull everything from the high-speed cache rather than recalculating
        ra_h = _cached_coords['ra_h']
        dec_d = _cached_coords['dec_d']
        alt_deg = _cached_coords['alt_deg']
        az_deg = _cached_coords['az_deg']
        sidereal = _cached_coords['lst_h']

        # Common device properties
        properties = {
            # ── Connection ──
            'connected':         True,
            'name':              DEVICE_NAME,
            'description':       'ARIES 104CM Telescope via STCS',
            'driverinfo':        'STCS Alpaca Driver v1.0',
            'driverversion':     '1.0',
            'interfaceversion':  3,
            'supportedactions':  [],

            # ── Capabilities ──
            'canfindhome':       False,
            'canpark':           False,
            'canpulseguide':     False,
            'cansetdeclinationrate': False,
            'cansetguiderates':  False,
            'cansetpark':        False,
            'cansetpierside':    False,
            'cansetrightascensionrate': False,
            'cansettracking':    True,
            'canslew':           True,
            'canslewaltaz':      False,
            'canslewaltazasync': False,
            'canslewasync':      True,
            'cansync':           True,
            'cansyncaltaz':      False,
            'canunpark':         False,
            'canmoveaxis':       False,

            # ── Alignment ──
            'alignmentmode':     1,  # algPolar
            'equatorialsystem':  1,  # equTopocentric (J2000 would be 2)

            # ── Coordinates ──
            'rightascension':    ra_h,
            'declination':       dec_d,
            'siderealtime':      sidereal,

            # ── Altitude/Azimuth ──
            'altitude':          alt_deg,
            'azimuth':           az_deg,

            # ── State ──
            'tracking':          ms.tracking_active if ms else False,
            'trackingrate':      0,  # driveSidereal
            'trackingrates':     [0],  # [driveSidereal]
            'slewing':           ms.is_slewing if ms else False,
            'athome':            False,
            'atpark':            False,
            'ispulseguiding':    False,
            'sideofpier':        0,  # pierEast

            # ── Target ──
            'targetrightascension': getattr(ms, '_target_ra_h', ra_h) if ms else 0.0,
            'targetdeclination':    getattr(ms, '_target_dec_d', dec_d) if ms else 0.0,

            # ── Site info ──
            'sitelatitude':      29.3607,  # ARIES Nainital
            'sitelongitude':     79.4571,
            'siteelevation':     1951.0,
            'utcdate':           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),

            # ── Axis rates ──
            'axisrates':         [],

            # ── Guiding (not supported) ──
            'guideratedeclination':    0.0,
            'guideraterightascension': 0.0,
            'declinationrate':         0.0,
            'rightascensionrate':      0.0,

            # ── Does move axis ──
            'doesrefraction':    False,
        }

        if prop_lower in properties:
            return self._json_response({"Value": properties[prop_lower]}, client_tid)
        else:
            logger.warning(f"Alpaca GET unknown property: {prop}")
            return self._error_response(400, f"Unknown property: {prop}", client_tid,
                                       error_number=0x400, error_message=f"Property '{prop}' is not implemented")

    # ═══════════════════════════════════════════════════════════
    # TELESCOPE PUT methods
    # ═══════════════════════════════════════════════════════════
    def _handle_telescope_put(self, method, params, client_tid):
        ms = _motion_state
        se = _slew_engine

        if method == 'connected':
            # Accept connection request
            connected = params.get('connected', 'true').lower() == 'true'
            logger.info(f"Alpaca: Connected = {connected}")
            return self._json_response({}, client_tid)

        elif method == 'tracking':
            tracking = params.get('tracking', 'false').lower() == 'true'
            if tracking:
                ms.activate_tracking()
            else:
                ms.deactivate_tracking()
            logger.info(f"Alpaca: Tracking = {tracking}")
            return self._json_response({}, client_tid)

        elif method == 'targetrightascension':
            ms._target_ra_h = float(params.get('targetrightascension', 0))
            return self._json_response({}, client_tid)

        elif method == 'targetdeclination':
            ms._target_dec_d = float(params.get('targetdeclination', 0))
            return self._json_response({}, client_tid)

        elif method == 'slewtocoordinatesasync':
            ra_h = float(params.get('rightascension', 0))
            dec_d = float(params.get('declination', 0))
            ra_deg = ra_h * 15.0
            ms._target_ra_h = ra_h
            ms._target_dec_d = dec_d
            ok, msg = se.start_slew(ra_deg, dec_d)
            logger.info(f"Alpaca: SlewToCoordinatesAsync RA={ra_h:.4f}h DEC={dec_d:.4f}° → {msg}")
            if ok:
                return self._json_response({}, client_tid)
            else:
                return self._error_response(400, msg, client_tid,
                                           error_number=0x40B, error_message=msg)

        elif method == 'slewtocoordinates':
            ra_h = float(params.get('rightascension', 0))
            dec_d = float(params.get('declination', 0))
            ra_deg = ra_h * 15.0
            ms._target_ra_h = ra_h
            ms._target_dec_d = dec_d
            ok, msg = se.start_slew(ra_deg, dec_d)
            logger.info(f"Alpaca: SlewToCoordinates RA={ra_h:.4f}h DEC={dec_d:.4f}° → {msg}")
            if ok:
                return self._json_response({}, client_tid)
            else:
                return self._error_response(400, msg, client_tid,
                                           error_number=0x40B, error_message=msg)

        elif method == 'synctocoordinates':
            ra_h = float(params.get('rightascension', 0))
            dec_d = float(params.get('declination', 0))
            logger.info(f"Alpaca: SyncToCoordinates RA={ra_h:.4f}h DEC={dec_d:.4f}°")
            # TODO: implement actual sync
            return self._json_response({}, client_tid)

        elif method == 'abortslew':
            se.abort()
            ms.emergency_stop()
            logger.info("Alpaca: AbortSlew")
            return self._json_response({}, client_tid)

        elif method == 'utcdate':
            # Accept but ignore UTC date sets
            return self._json_response({}, client_tid)

        elif method == 'sitelatitude':
            return self._json_response({}, client_tid)

        elif method == 'sitelongitude':
            return self._json_response({}, client_tid)

        elif method == 'siteelevation':
            return self._json_response({}, client_tid)

        else:
            logger.warning(f"Alpaca PUT unknown method: {method}")
            return self._error_response(400, f"Method '{method}' not implemented", client_tid,
                                       error_number=0x400, error_message=f"Method '{method}' not implemented")

    # ═══════════════════════════════════════════════════════════
    # RESPONSE HELPERS
    # ═══════════════════════════════════════════════════════════
    def _json_response(self, extra_data, client_tid, status=200):
        response = {
            "ClientTransactionID": client_tid,
            "ServerTransactionID": _next_server_tid(),
            "ErrorNumber": 0,
            "ErrorMessage": "",
        }
        response.update(extra_data)
        body = json.dumps(response).encode('utf-8')

        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, status, message, client_tid, error_number=0, error_message=""):
        response = {
            "ClientTransactionID": client_tid,
            "ServerTransactionID": _next_server_tid(),
            "ErrorNumber": error_number,
            "ErrorMessage": error_message or message,
        }
        body = json.dumps(response).encode('utf-8')

        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _get_radec():
    """Get current RA (hours) and DEC (degrees)."""
    if _astro and _motion_state:
        # We can use the cached method here since it's now called from AlpacaCacheThread
        lst_h = _astro.get_current_lst_hours_cached()
        ha_h = _motion_state.sim_ha_deg / 15.0
        ra = (lst_h - ha_h) % 24.0
        dec = _motion_state.sim_dec_deg
        return ra, dec
    return 0.0, 0.0

class AlpacaCacheThread(threading.Thread):
    """
    Background thread that caches coordinates for Alpaca HTTP responses.

    Two update tiers to avoid blocking Cartes du Ciel polling:
      - RA / DEC / LST:  10Hz (pure arithmetic — no Astropy)
      - Alt / Az:         2Hz (expensive Astropy SkyCoord transforms)
    """
    def __init__(self):
        super().__init__(daemon=True)
        self._running = True

    def run(self):
        altaz_interval = 0.5  # seconds between Alt/Az recalculations
        last_altaz_time = 0.0

        while self._running:
            if _astro and _motion_state:
                # ── Fast path (10Hz): RA, DEC, LST — pure arithmetic ──
                ra_h, dec_d = _get_radec()
                clamped_dec = max(-90.0, min(90.0, dec_d))
                _cached_coords['ra_h'] = ra_h
                _cached_coords['dec_d'] = clamped_dec
                _cached_coords['lst_h'] = _astro.get_current_lst_hours_cached()

                # ── Slow path (2Hz): Alt/Az — expensive Astropy transform ──
                now = time.monotonic()
                if now - last_altaz_time >= altaz_interval:
                    last_altaz_time = now
                    try:
                        astro_params = _astro.calculate_parameters(ra_h, clamped_dec)
                        _cached_coords['alt_deg'] = astro_params.get("alt_deg", 0.0)
                        _cached_coords['az_deg'] = astro_params.get("az_deg", 0.0)
                    except Exception:
                        pass

            time.sleep(0.1)  # 10Hz main loop

    def stop(self):
        self._running = False


class AlpacaDiscoveryThread(threading.Thread):
    """
    UDP discovery responder on port 32227.
    Clients broadcast "alpacadiscovery1" and we respond with {"AlpacaPort": <port>}.
    """
    def __init__(self, alpaca_port):
        super().__init__(daemon=True)
        self.alpaca_port = alpaca_port
        self._running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)

        try:
            sock.bind(('0.0.0.0', 32227))
            logger.info("Alpaca Discovery listening on UDP 32227")
        except OSError as e:
            logger.warning(f"Alpaca Discovery bind failed: {e}")
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(256)
                msg = data.decode('utf-8', errors='replace').strip()
                if msg.startswith('alpacadiscovery'):
                    response = json.dumps({"AlpacaPort": self.alpaca_port}).encode('utf-8')
                    sock.sendto(response, addr)
                    logger.info(f"Alpaca Discovery: responded to {addr} with port {self.alpaca_port}")
            except socket.timeout:
                continue
            except OSError:
                break

        sock.close()

    def stop(self):
        self._running = False


class AlpacaServerThread(threading.Thread):
    """
    Main ASCOM Alpaca HTTP server thread.
    Runs in a background daemon thread.
    """
    def __init__(self, motion_state, slew_engine, astro):
        super().__init__(daemon=True)
        global _motion_state, _slew_engine, _astro
        _motion_state = motion_state
        _slew_engine = slew_engine
        _astro = astro
        self._running = True
        self._httpd = None
        self._discovery = None

    def run(self):
        host = os.environ.get("ALPACA_HOST", "0.0.0.0")
        port = int(os.environ.get("ALPACA_PORT", "11111"))

        # Start UDP discovery responder
        self._discovery = AlpacaDiscoveryThread(port)
        self._discovery.start()

        # Start coordinate cache updater
        self._cache_thread = AlpacaCacheThread()
        self._cache_thread.start()

        # Start HTTP server
        try:
            self._httpd = ThreadingHTTPServer((host, port), AlpacaRequestHandler)
            self._httpd.daemon_threads = True
            logger.info(f"Alpaca HTTP Server listening on {host}:{port}. Concurrency enabled.")
        except OSError as e:
            logger.error(f"Alpaca Server bind failed: {e}")
            return

        # serve_forever handles concurrent requests in daemon threads
        # vastly improving responsiveness to Cartes du Ciel
        self._httpd.serve_forever()

        logger.info("Alpaca Server stopped.")

    def stop(self):
        self._running = False
        if self._discovery:
            self._discovery.stop()
        if hasattr(self, '_cache_thread'):
            self._cache_thread.stop()
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
