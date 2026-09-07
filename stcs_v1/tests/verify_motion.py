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

dec_sn = config['connections']['dec_controller']['serial_number']
dome_sn = config['connections']['dome_controller']['serial_number']

def monitor_motion():
    print(f"--- MOTION VERIFICATION MONITOR ---")
    print(f"DEC Board SN:  {dec_sn}")
    print(f"DOME Board SN: {dome_sn}")
    print("-----------------------------------")
    print("Connecting to hardware...")

    dec_driver = SmartSerial(dec_sn)
    dome_driver = SmartSerial(dome_sn)

    try:
        dec_driver.connect()
        dome_driver.connect()
        print("\nSUCCESS: Connected to both controllers.")
        print("Starting monitoring loop. PLEASE MANUALLY MOVE THE TELESCOPE/DOME NOW.")
        print("Press Ctrl+C to stop.\n")
        print(f"{'TIMESTAMP':<15} | {'DEC RAW':<15} | {'DOME RAW':<15}")
        print("-" * 50)

        while True:
            # Read DEC
            # Clear buffer to ensure we aren't reading old data
            dec_driver.connection.reset_input_buffer()
            dec_raw = dec_driver.send_command("A'\n") # Standard 'A' command
            
            # Read DOME
            dome_driver.connection.reset_input_buffer()
            dome_raw = dome_driver.send_command("A'\n") # Standard 'A' command

            # Get timestamp
            ts = time.strftime("%H:%M:%S")

            # Print simple table row
            print(f"{ts:<15} | {dec_raw:<15} | {dome_raw:<15}")
            
            time.sleep(0.5) # 2Hz update rate

    except KeyboardInterrupt:
        print("\nStopping monitor...")
    except Exception as e:
        print(f"\nERROR: {e}")
    finally:
        print("Closing connections...")
        if dec_driver.connection and dec_driver.connection.is_open:
            dec_driver.close()
        if dome_driver.connection and dome_driver.connection.is_open:
            dome_driver.close()

if __name__ == "__main__":
    monitor_motion()