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

dome_sn = config['connections']['dome_controller']['serial_number']

# 2. Initialize Driver
print(f"Attempting to connect to DOME Board (SN: {dome_sn})...")
dome_driver = SmartSerial(dome_sn)

try:
    dome_driver.connect()
    
    # --- COMMAND 1: VERSION ---
    print("Sending Version Command (v)...")
    dome_driver.connection.reset_input_buffer() 
    response = dome_driver.send_command("v'\n") 
    print(f"DOME RESPONSE: {response}")

    # --- COMMAND 2: READ POSITION (LOOP) ---
    print("\nReading Position 5 times (to check stability)...")
    
    for i in range(5):
        # Based on aries1.c: enc_dome_enquiry uses "A'\'\n"
        response = dome_driver.send_command("A'\n")
        print(f"DOME RAW POSITION [{i+1}]: {response}")
        time.sleep(0.5)

except Exception as e:
    print(f"TEST FAILED: {e}")

finally:
    dome_driver.close()