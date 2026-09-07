# src/workers/indi_telescope_driver.py
"""
Pure-Python INDI Telescope Server for Cartes du Ciel 4.2.1 on Windows.

Compatible with CdC's Pascal INDI client which:
  1. Uses RecvTerminated(LF) — each XML element must be on ONE LINE ending with \n
  2. Wraps received lines in <INDIMSG>...</INDIMSG> before parsing with ReadXMLFile
  3. Looks for DRIVER_INFO.DRIVER_INTERFACE=1 to identify telescope
  4. Requires non-empty 'device' attribute on every defXxxVector

Protocol flow:
  Client → <getProperties version="1.7"/>\n
  Server → <defTextVector device="X" name="DRIVER_INFO" ...>...</defTextVector>\n
  Server → <defSwitchVector device="X" name="CONNECTION" ...>...</defSwitchVector>\n
  Server → <defNumberVector device="X" name="EQUATORIAL_EOD_COORD" ...>...</defNumberVector>\n
  ...
  Server → (periodic) <setNumberVector device="X" ...>RA/DEC</setNumberVector>\n
"""
import os
import socket
import threading
import time
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger("INDIServer")

DEVICE_NAME = "ARIES 104CM"
TELESCOPE_INTERFACE = 1


def is_indi_available():
    return True


class INDIClientHandler:
    """Handles a single INDI client connection (e.g., Cartes du Ciel)."""

    def __init__(self, conn, addr, motion_state, slew_engine, astro, running_flag):
        self.conn = conn
        self.addr = addr
        self.motion_state = motion_state
        self.slew_engine = slew_engine
        self.astro = astro
        self._running = running_flag
        self.coord_set_mode = "SLEW"
        self.definitions_sent = False
        self.alive = True

    def handle(self):
        """Main client handling loop with separate receive and push."""
        # TCP_NODELAY: disable Nagle's algorithm for immediate send
        self.conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.conn.settimeout(1.0)

        logger.info(f"INDI: Handling client {self.addr}")

        # Start receiver thread
        recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        recv_thread.start()

        # Push loop runs in this thread
        try:
            while self._running() and self.alive:
                if self.definitions_sent:
                    self._send_position_update()
                time.sleep(0.5)  # 2 Hz position updates
        except Exception as e:
            logger.error(f"INDI push loop error: {e}")
        finally:
            self.alive = False
            logger.info(f"INDI: Client {self.addr} disconnected")
            try:
                self.conn.close()
            except Exception:
                pass

    def _receive_loop(self):
        """Receive thread: reads lines from client and processes them."""
        buffer = b""
        try:
            while self._running() and self.alive:
                try:
                    data = self.conn.recv(4096)
                    if not data:
                        self.alive = False
                        break
                    buffer += data
                    logger.debug(f"INDI RX raw: {data!r}")

                    # Process complete lines (CdC sends \n terminated lines)
                    while b'\n' in buffer or b'/>' in buffer:
                        # Try to find a complete XML element
                        # CdC sends: <getProperties version="1.7"/>\n
                        line_end = buffer.find(b'\n')
                        if line_end >= 0:
                            line = buffer[:line_end].strip()
                            buffer = buffer[line_end + 1:]
                        else:
                            # No newline yet, try to find self-closing tag
                            sc_end = buffer.find(b'/>')
                            if sc_end >= 0:
                                line = buffer[:sc_end + 2].strip()
                                buffer = buffer[sc_end + 2:]
                            else:
                                break

                        if line:
                            self._process_line(line)

                except socket.timeout:
                    continue
                except (ConnectionError, OSError):
                    self.alive = False
                    break
        except Exception as e:
            logger.error(f"INDI recv error: {e}")
            self.alive = False

    def _process_line(self, line_bytes):
        """Process a single XML line from the client."""
        try:
            text = line_bytes.decode('utf-8', errors='replace').strip()
            if not text:
                return

            logger.info(f"INDI RX: {text[:200]}")

            # Check for closing tags to handle multi-line XML
            # (though CdC typically sends all on one line)
            elem = ET.fromstring(text)
            self._process_element(elem)

        except ET.ParseError as e:
            logger.debug(f"INDI: XML parse error (partial?): {e}")
        except Exception as e:
            logger.error(f"INDI: Process error: {e}")

    def _process_element(self, elem):
        """Process a parsed INDI XML element."""
        tag = elem.tag
        logger.info(f"INDI: CMD <{tag}> device='{elem.get('device', '')}' name='{elem.get('name', '')}'")

        if tag == "getProperties":
            self._send_device_definitions()

        elif tag == "newSwitchVector":
            device = elem.get("device", "")
            name = elem.get("name", "")
            if device and device != DEVICE_NAME:
                return

            if name == "CONNECTION":
                for sw in elem.findall("oneSwitch"):
                    sw_name = sw.get("name", "")
                    sw_val = (sw.text or "").strip()
                    if sw_name == "CONNECT" and sw_val == "On":
                        self._send_xml(
                            f'<setSwitchVector device="{DEVICE_NAME}" name="CONNECTION" state="Ok" timestamp="{self._ts()}">'
                            f'<oneSwitch name="CONNECT">On</oneSwitch>'
                            f'<oneSwitch name="DISCONNECT">Off</oneSwitch>'
                            f'</setSwitchVector>'
                        )
                        logger.info("INDI: Device CONNECTED")
                    elif sw_name == "DISCONNECT" and sw_val == "On":
                        self._send_xml(
                            f'<setSwitchVector device="{DEVICE_NAME}" name="CONNECTION" state="Idle" timestamp="{self._ts()}">'
                            f'<oneSwitch name="CONNECT">Off</oneSwitch>'
                            f'<oneSwitch name="DISCONNECT">On</oneSwitch>'
                            f'</setSwitchVector>'
                        )

            elif name == "ON_COORD_SET":
                members = ""
                for sw in elem.findall("oneSwitch"):
                    sw_name = sw.get("name", "")
                    sw_val = (sw.text or "").strip()
                    members += f'<oneSwitch name="{sw_name}">{sw_val}</oneSwitch>'
                    if sw_val == "On":
                        self.coord_set_mode = sw_name
                self._send_xml(
                    f'<setSwitchVector device="{DEVICE_NAME}" name="ON_COORD_SET" state="Ok" timestamp="{self._ts()}">'
                    f'{members}</setSwitchVector>'
                )

            elif name == "TELESCOPE_ABORT_MOTION":
                self.slew_engine.abort()
                self.motion_state.emergency_stop()
                self._send_xml(
                    f'<setSwitchVector device="{DEVICE_NAME}" name="TELESCOPE_ABORT_MOTION" state="Ok" timestamp="{self._ts()}">'
                    f'<oneSwitch name="ABORT">Off</oneSwitch></setSwitchVector>'
                )
                logger.info("INDI: ABORT")

        elif tag == "newNumberVector":
            device = elem.get("device", "")
            name = elem.get("name", "")
            if device and device != DEVICE_NAME:
                return

            if name == "EQUATORIAL_EOD_COORD":
                ra_h = dec_d = None
                for num in elem.findall("oneNumber"):
                    if num.get("name") == "RA":
                        ra_h = float((num.text or "0").strip())
                    elif num.get("name") == "DEC":
                        dec_d = float((num.text or "0").strip())

                if ra_h is not None and dec_d is not None:
                    ra_deg = ra_h * 15.0
                    if self.coord_set_mode in ("SLEW", "TRACK"):
                        ok, msg = self.slew_engine.start_slew(ra_deg, dec_d)
                        st = "Busy" if ok else "Alert"
                        logger.info(f"INDI: SLEW RA={ra_h:.4f}h DEC={dec_d:.4f}° → {msg}")
                    else:
                        st = "Ok"
                        logger.info(f"INDI: SYNC RA={ra_h:.4f}h DEC={dec_d:.4f}°")

                    self._send_xml(
                        f'<setNumberVector device="{DEVICE_NAME}" name="EQUATORIAL_EOD_COORD" state="{st}" timestamp="{self._ts()}">'
                        f'<oneNumber name="RA">{ra_h:.6f}</oneNumber>'
                        f'<oneNumber name="DEC">{dec_d:.6f}</oneNumber>'
                        f'</setNumberVector>'
                    )

    # ─── DEVICE DEFINITIONS ────────────────────────────────────

    def _send_device_definitions(self):
        """
        Send all defXxxVector properties. Each must be a SINGLE LINE ending with \n
        because CdC uses RecvTerminated(LF) + wraps in <INDIMSG>.
        """
        ra, dec = self._get_radec()
        ts = self._ts()

        # Order matters: DRIVER_INFO first so CdC identifies device type
        defs = [
            # 1. DRIVER_INFO — tells CdC this is a telescope (interface=1)
            f'<defTextVector device="{DEVICE_NAME}" name="DRIVER_INFO" label="Driver Info" group="Options" state="Ok" perm="ro" timestamp="{ts}">'
            f'<defText name="DRIVER_NAME" label="Name">{DEVICE_NAME}</defText>'
            f'<defText name="DRIVER_EXEC" label="Exec">indi_stcs_telescope</defText>'
            f'<defText name="DRIVER_VERSION" label="Version">1.0</defText>'
            f'<defText name="DRIVER_INTERFACE" label="Interface">{TELESCOPE_INTERFACE}</defText>'
            f'</defTextVector>',

            # 2. CONNECTION
            f'<defSwitchVector device="{DEVICE_NAME}" name="CONNECTION" label="Connection" group="Main Control" state="Ok" perm="rw" rule="OneOfMany" timestamp="{ts}">'
            f'<defSwitch name="CONNECT" label="Connect">On</defSwitch>'
            f'<defSwitch name="DISCONNECT" label="Disconnect">Off</defSwitch>'
            f'</defSwitchVector>',

            # 3. EQUATORIAL_EOD_COORD
            f'<defNumberVector device="{DEVICE_NAME}" name="EQUATORIAL_EOD_COORD" label="Eq. Coordinates" group="Main Control" state="Ok" perm="rw" timestamp="{ts}">'
            f'<defNumber name="RA" label="RA (Hours)" format="%10.6m" min="0" max="24" step="0">{ra:.6f}</defNumber>'
            f'<defNumber name="DEC" label="DEC (Degrees)" format="%10.6m" min="-90" max="90" step="0">{dec:.6f}</defNumber>'
            f'</defNumberVector>',

            # 4. ON_COORD_SET
            f'<defSwitchVector device="{DEVICE_NAME}" name="ON_COORD_SET" label="On Set" group="Main Control" state="Ok" perm="rw" rule="OneOfMany" timestamp="{ts}">'
            f'<defSwitch name="SLEW" label="Slew">On</defSwitch>'
            f'<defSwitch name="TRACK" label="Track">Off</defSwitch>'
            f'<defSwitch name="SYNC" label="Sync">Off</defSwitch>'
            f'</defSwitchVector>',

            # 5. TELESCOPE_ABORT_MOTION
            f'<defSwitchVector device="{DEVICE_NAME}" name="TELESCOPE_ABORT_MOTION" label="Abort" group="Main Control" state="Ok" perm="rw" rule="AtMostOne" timestamp="{ts}">'
            f'<defSwitch name="ABORT" label="Abort Motion">Off</defSwitch>'
            f'</defSwitchVector>',
        ]

        # Send each definition as a SINGLE LINE + \n, flushed immediately
        for xml_line in defs:
            self._send_xml(xml_line)
            time.sleep(0.01)  # Tiny delay between defs for CdC parser

        self.definitions_sent = True
        logger.info(f"INDI: Sent {len(defs)} property definitions")

    # ─── POSITION PUSH ─────────────────────────────────────────

    def _send_position_update(self):
        ra, dec = self._get_radec()
        st = "Busy" if self.motion_state.is_slewing else "Ok"
        self._send_xml(
            f'<setNumberVector device="{DEVICE_NAME}" name="EQUATORIAL_EOD_COORD" state="{st}" timestamp="{self._ts()}">'
            f'<oneNumber name="RA">{ra:.6f}</oneNumber>'
            f'<oneNumber name="DEC">{dec:.6f}</oneNumber>'
            f'</setNumberVector>'
        )

    # ─── HELPERS ───────────────────────────────────────────────

    def _get_radec(self):
        lst_h = self.astro.get_current_lst_hours()
        ha_h = self.motion_state.sim_ha_deg / 15.0
        ra = (lst_h - ha_h) % 24.0
        dec = self.motion_state.sim_dec_deg
        return ra, dec

    def _ts(self):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    def _send_xml(self, xml_str):
        """Send a single XML element as one line + \\n. TCP_NODELAY ensures immediate flush."""
        try:
            # Ensure no internal newlines (must be one line for CdC)
            line = xml_str.replace('\n', '').replace('\r', '') + '\n'
            self.conn.sendall(line.encode('utf-8'))
        except (ConnectionError, OSError):
            self.alive = False


class INDIServerThread(threading.Thread):
    """INDI TCP server. Runs in a background daemon thread."""

    def __init__(self, motion_state, slew_engine, astro):
        super().__init__(daemon=True)
        self.motion_state = motion_state
        self.slew_engine = slew_engine
        self.astro = astro
        self._running = True
        self._server_socket = None

    def run(self):
        host = os.environ.get("INDI_HOST", "127.0.0.1")
        port = int(os.environ.get("INDI_PORT", "7624"))

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._server_socket.bind((host, port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(1.0)
            logger.info(f"INDI Server listening on {host}:{port}")
        except OSError as e:
            logger.error(f"INDI Server bind failed: {e}")
            return

        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                logger.info(f"INDI: Client connected from {addr}")
                handler = INDIClientHandler(
                    conn, addr,
                    self.motion_state, self.slew_engine, self.astro,
                    running_flag=lambda: self._running
                )
                t = threading.Thread(target=handler.handle, daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                break

        logger.info("INDI Server stopped.")

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
