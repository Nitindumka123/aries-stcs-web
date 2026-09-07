import json
import sys
import os
import time

# --- PATH FIX ---
# Add the project root directory (parent of 'tests') to Python's search path
# so it can find the 'src' module.
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

dec_sn = config['connections']['dec_controller']['serial_number']

# 2. Initialize Driver
print(f"Attempting to connect to DEC Board (SN: {dec_sn})...")
dec_driver = SmartSerial(dec_sn)

try:
    dec_driver.connect()
    
    # --- COMMAND 1: VERSION ---
    print("Sending Version Command (v)...")
    dec_driver.connection.reset_input_buffer() 
    response = dec_driver.send_command("v'\n") 
    print(f"DEC RESPONSE: {response}")

    # --- COMMAND 2: READ POSITION (LOOP) ---
    print("\nReading Position 5 times (to check stability)...")
    
    for i in range(5):
        # Based on aries1.c: enc_dec_enquiry_PPR_AB_incremental uses "A'\'\n"
        response = dec_driver.send_command("A'\n")
        print(f"DEC RAW POSITION [{i+1}]: {response}")
        time.sleep(0.5)

except Exception as e:
    print(f"TEST FAILED: {e}")

finally:
    dec_driver.close()