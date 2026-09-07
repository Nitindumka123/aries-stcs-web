import serial
import serial.tools.list_ports
import time
import logging

# Configure logging to track hardware issues
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartSerial")

class SmartSerial:
    def __init__(self, target_serial_number, baud_rate=115200, timeout=1):
        """
        Initializes the SmartSerial connection manager.
        :param target_serial_number: The unique USB ID of the Arduino R4.
        :param baud_rate: 115200 (Ignored by R4 Native USB but good practice).
        :param timeout: Read timeout in seconds.
        """
        self.target_sn = target_serial_number
        self.baud = baud_rate
        self.timeout = timeout
        self.connection = None
        self.port_name = None

    def connect(self):
        """
        Scans all USB ports to find the board with the matching Serial Number.
        Then establishes the connection.
        """
        logger.info(f"Scanning for device with Serial Number: {self.target_sn}...")
        
        ports = serial.tools.list_ports.comports()
        found_port = None
        
        for p in ports:
            if p.serial_number == self.target_sn:
                found_port = p.device
                break
        
        if not found_port:
            logger.error(f"Device {self.target_sn} NOT FOUND! Is it plugged in?")
            raise Exception(f"Hardware Board with ID {self.target_sn} not found!")

        self.port_name = found_port
        logger.info(f"Found target on {self.port_name}. Connecting...")

        try:
            self.connection = serial.Serial(
                self.port_name, 
                self.baud, 
                timeout=self.timeout,
                write_timeout=self.timeout,
                stopbits=serial.STOPBITS_TWO  # CRITICAL: From aries1.c (CSTOPB)
            )
            
            # R4 Minima Specific: Clear any garbage in the USB buffer
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()
            
            # Allow board to stabilize. Extend to 1.5s to give the Arduino
            # time to finish any bootloader chatter and flush its TX buffer
            # before we start issuing commands. Encoder Arduinos continuously
            # stream data; without this wait, the RX buffer fills with
            # stale frames that corrupt the first few reads.
            time.sleep(1.5)

            # Drain everything the Arduino sent during the wait
            if self.connection.in_waiting > 0:
                self.connection.read(self.connection.in_waiting)

            logger.info("Connection Successful.")
            
        except serial.SerialException as e:
            logger.error(f"Failed to open {self.port_name}: {e}")
            raise

    def send_command(self, cmd_str):
        """
        Sends a command string and waits for a response (Sync).

        Uses a "discard-first, read-clean" pattern to eliminate stale buffer
        contamination. Because the RA encoder Arduino continuously streams data,
        there may be a partial packet in-flight when we write our command. If
        we read immediately, we get a corrupted response (tail of old packet +
        start of new one). Sending the command twice and discarding the first
        response ensures we always read a clean, command-aligned packet.

        :param cmd_str: Command like "R'\\n" or "A'\\n"
        :return: Cleaned string response, or None on timeout/error.
        """
        if not self.connection or not self.connection.is_open:
            logger.error("Attempted to send command while disconnected.")
            return None

        try:
            # ── Phase 1: Drain ──────────────────────────────────────────────
            # Clear any bytes that arrived since the last command (stale data
            # from continuous streaming or buffered echo packets).
            if self.connection.in_waiting > 0:
                self.connection.read(self.connection.in_waiting)

            # ── Phase 2: Send + Discard (alignment pulse) ───────────────────
            # Write the command and read (discard) one response. This consumes
            # any partial packet that was already in transit when we wrote.
            self.connection.write(cmd_str.encode('utf-8'))
            self.connection.flush()

            saved_timeout = self.connection.timeout
            self.connection.timeout = 0.2
            _ = self.connection.read_until(b'\n')   # Discard — may be partial

            # ── Phase 3: Send + Read (clean response) ───────────────────────
            # Now send the command again. This time the buffer is aligned and
            # we read a guaranteed fresh, complete response.
            self.connection.write(cmd_str.encode('utf-8'))
            self.connection.flush()
            response = self.connection.read_until(b'\n')
            self.connection.timeout = saved_timeout

            # Fallback: if read_until timed out, grab whatever bytes arrived
            if not response and self.connection.in_waiting > 0:
                response = self.connection.read(self.connection.in_waiting)

            return response.decode('utf-8').strip() if response else None

        except Exception as e:
            logger.error(f"Communication Error: {e}")
            return None

    def close(self):
        if self.connection:
            self.connection.close()
            logger.info("Connection Closed.")