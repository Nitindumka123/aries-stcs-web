import socket
import json
import logging
import time
import os
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WeatherWorker")

class WeatherWorker(QThread):
    """
    Listens for Weather Data broadcasts on UDP Port 12344.
    """
    weather_updated = pyqtSignal(dict)  # Emits parsed data {temp, humidity, dewpoint}
    safety_alert = pyqtSignal(str)      # Emits critical messages (e.g., "High Humidity!")
    log_message = pyqtSignal(str, str)  # For UI status bar logs

    def __init__(self, port=12344, log_file_path=None):
        super().__init__()
        self.port = port
        self.running = False
        self.sock = None
        self.log_file_path = log_file_path
        self.humidity_limit = 70.0 # Safety Threshold

    def set_log_file_path(self, path):
        self.log_file_path = path

    def run(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 1. Set Timeout: Wakes up every 1.0s to check if self.running is still True
        self.sock.settimeout(1.0)
        
        try:
            self.sock.bind(('0.0.0.0', self.port))
            self.log_message.emit("INFO", f"Weather Monitor listening on UDP {self.port}...")
            
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024) 
                    
                    # Parse Data
                    raw_str = data.decode('utf-8').strip()
                    parts = raw_str.split(',')
                    
                    if len(parts) >= 3:
                        try:
                            temp = float(parts[0])
                            humidity = float(parts[1])
                            dew_point = float(parts[2])
                            
                            weather_data = {
                                "timestamp": datetime.now().isoformat(),
                                "temp_c": temp,
                                "humidity_percent": humidity,
                                "dew_point_c": dew_point
                            }
                            
                            # Emit Update
                            self.weather_updated.emit(weather_data)
                            
                            # Safety Check
                            # if humidity > self.humidity_limit:
                            #     alert_msg = f"CRITICAL: Humidity {humidity}% > {self.humidity_limit}%. Closing Dome Slit!"
                            #     self.safety_alert.emit(alert_msg)
                                # self.trigger_dome_close()
                            
                            # File Logging
                            if self.log_file_path:
                                self.append_to_log(weather_data)
                                
                        except ValueError:
                            logger.warning(f"Malformed weather data: {raw_str}")

                except socket.timeout:
                    # Normal timeout, loop back to check self.running
                    continue

                except OSError as e:
                    # 2. Graceful Exit: If the socket was closed while we were waiting,
                    # and we are stopping, this is NOT an error. It's the stop signal.
                    if not self.running:
                        break
                    logger.error(f"Weather UDP Error: {e}")
                    # Brief sleep to avoid spamming logs if persistent error
                    time.sleep(1)

                except Exception as e:
                    logger.error(f"General Weather Worker Error: {e}")
                    
        except Exception as e:
            self.log_message.emit("ERROR", f"Weather Bind Failed: {e}")
        finally:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass

    def append_to_log(self, data):
        """Appends the weather data point to a JSON list file."""
        try:
            if not os.path.exists(self.log_file_path):
                with open(self.log_file_path, 'w') as f:
                    json.dump([], f)
            
            with open(self.log_file_path, 'r+') as f:
                try:
                    file_data = json.load(f)
                except json.JSONDecodeError:
                    file_data = []
                
                file_data.append(data)
                f.seek(0)
                json.dump(file_data, f, indent=2)
        except Exception as e:
            logger.error(f"Log File Error: {e}")

    def trigger_dome_close(self):
        logger.warning("SAFETY INTERLOCK: Closing Dome due to weather conditions.")

    def stop(self):
        self.running = False
        # Force close the socket to break the blocking recvfrom immediately
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.wait()