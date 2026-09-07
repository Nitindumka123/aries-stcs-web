# stcs_v1/src/drivers/gps/gps_driver.py
import serial
import serial.tools.list_ports
import pynmea2
import logging
import time
from datetime import datetime

logger = logging.getLogger("GPSDriver")

class GPSDriver:
    """
    Hardware driver for the LOCOSYS MC-1010-V3b EVK.
    Reads NMEA 0183 sentences at 115200 bps and aggregates data.
    Features Auto-Discovery via NMEA Sniffing.
    """
    def __init__(self, port="AUTO", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.connection = None
        
        # State buffers to hold aggregated data before sending to UI
        self.current_data = {
            "fix_quality": 0, # 0=Invalid, 1=GPS fix, 2=DGPS
            "latitude": 0.0,
            "longitude": 0.0,
            "altitude": 0.0,
            "utc_time": None,
            "speed_knots": 0.0,
            "course_true": 0.0,
            "satellites_in_view": 0,
            "satellite_details": [] # List of dicts: prn, elevation, azimuth, snr
        }
        
        # Buffer for multi-line GSV (Satellites in View) messages
        self._gsv_buffer = []

    def _auto_discover_port(self):
        """
        Scans all available COM ports and listens for NMEA strings.
        Returns the COM port name if a GPS is found, else None.
        """
        logger.info("Starting Auto-Discovery for GPS Module...")
        available_ports = serial.tools.list_ports.comports()
        
        for p in available_ports:
            logger.debug(f"Testing port {p.device} for NMEA stream...")
            try:
                # Open port temporarily to listen
                with serial.Serial(p.device, self.baudrate, timeout=1) as test_conn:
                    start_time = time.time()
                    # Listen for up to 2 seconds (GPS updates at 1Hz, so 2s is enough)
                    while time.time() - start_time < 2.0:
                        line = test_conn.readline().decode('ascii', errors='ignore').strip()
                        
                        # Check if the line looks like a valid NMEA sentence
                        if line.startswith('$G') or line.startswith('$GN') or line.startswith('$GP'):
                            try:
                                # Validate it parses correctly
                                pynmea2.parse(line)
                                logger.info(f"GPS auto-detected successfully on {p.device}!")
                                return p.device
                            except pynmea2.ParseError:
                                pass # Keep trying other lines if one is corrupted
            except Exception as e:
                # Port might be in use by an Arduino or inaccessible
                logger.debug(f"Skipping {p.device}: {e}")
                
        logger.error("Auto-Discovery failed. No GPS NMEA stream detected on any port.")
        return None

    def connect(self):
        try:
            # Run auto-discovery if port is set to "AUTO"
            if self.port.upper() == "AUTO":
                discovered_port = self._auto_discover_port()
                if discovered_port:
                    self.port = discovered_port
                else:
                    return False

            self.connection = serial.Serial(self.port, self.baudrate, timeout=1)
            logger.info(f"Connected to GPS on {self.port} at {self.baudrate} baud.")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to connect to GPS: {e}")
            return False

    def disconnect(self):
        if self.connection and self.connection.is_open:
            self.connection.close()
            logger.info("GPS Disconnected.")

    def read_and_parse(self):
        """
        Reads a line from the serial port, parses the NMEA sentence, 
        and updates the current_data dictionary.
        Returns the updated dictionary if a major update (GGA/RMC) occurred, else None.
        """
        if not self.connection or not self.connection.is_open:
            return None

        try:
            line = self.connection.readline().decode('ascii', errors='replace').strip()
            if not line.startswith('$'):
                return None

            msg = pynmea2.parse(line)
            data_updated = False

            # 1. GGA - Global Positioning System Fix Data
            if isinstance(msg, pynmea2.GGA):
                self.current_data["latitude"] = msg.latitude
                self.current_data["longitude"] = msg.longitude
                self.current_data["altitude"] = msg.altitude
                self.current_data["fix_quality"] = msg.gps_qual
                data_updated = True

            # 2. RMC - Recommended Minimum Specific GNSS Data (Time & Speed)
            elif isinstance(msg, pynmea2.RMC):
                self.current_data["utc_time"] = msg.datetime
                self.current_data["speed_knots"] = msg.spd_over_grnd
                self.current_data["course_true"] = msg.true_course
                data_updated = True

            # 3. GSV - GNSS Satellites in View (Comes in batches)
            elif isinstance(msg, pynmea2.GSV):
                # If it's the first message of a new batch, clear the buffer
                if msg.msg_num == 1:
                    self._gsv_buffer = []
                
                # Extract up to 4 satellites per GSV sentence
                for i in range(1, 5):
                    prn = getattr(msg, f'sv_prn_num_{i}', None)
                    el = getattr(msg, f'elevation_deg_{i}', None)
                    az = getattr(msg, f'azimuth_{i}', None)
                    snr = getattr(msg, f'snr_{i}', None)
                    
                    if prn and prn.strip():
                        self._gsv_buffer.append({
                            "prn": prn,
                            "elevation": float(el) if el else 0.0,
                            "azimuth": float(az) if az else 0.0,
                            "snr": int(snr) if snr else 0
                        })

                # If this is the last message in the batch, commit to current_data
                if msg.msg_num == msg.num_messages:
                    self.current_data["satellite_details"] = self._gsv_buffer.copy()
                    self.current_data["satellites_in_view"] = int(msg.num_sv_in_view)
                    data_updated = True

            return self.current_data if data_updated else None

        except pynmea2.ParseError:
            # Normal to get occasional incomplete strings when port first opens
            pass
        except Exception as e:
            logger.error(f"GPS Read Error: {e}")
            
        return None