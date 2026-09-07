import json
import sys
import os
import time

# --- PATH FIX ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
# ----------------

from src.drivers.mount.smart_serial import SmartSerial

# 1. Load Config
config_path = os.path.join(project_root, 'config', 'settings.json')
with open(config_path, 'r') as f:
    config = json.load(f)

ra_sn = config['connections']['ra_controller']['serial_number']

# 2. Initialize Driver
print(f"Attempting to connect to RA Board (SN: {ra_sn})...")
ra_driver = SmartSerial(ra_sn)

try:
    ra_driver.connect()
    
    # --- COMMAND 1: VERSION ---
    # Python string "v'\n" sends exactly 3 bytes: v, ', \n
    print("Sending Version Command (v)...")
    # Clear buffer first to ensure we get fresh data
    ra_driver.connection.reset_input_buffer() 
    response = ra_driver.send_command("v'\n") 
    print(f"RA RESPONSE: {response}")

    # --- COMMAND 2: READ POSITION (LOOP) ---
    print("\nReading Position 5 times (to check stability)...")
    
    for i in range(5):
        # We assume the command is R'\n based on aries1.c
        # If 'A' command is used for DEC, 'R' is likely RA.
        response = ra_driver.send_command("R'\n")
        print(f"RA RAW POSITION [{i+1}]: {response}")
        time.sleep(0.5)

except Exception as e:
    print(f"TEST FAILED: {e}")

finally:
    ra_driver.close()