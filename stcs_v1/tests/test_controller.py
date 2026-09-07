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

def test_controller(name, sn):
    print(f"\n--- Testing {name} Board (SN: {sn}) ---")
    driver = SmartSerial(sn)
    try:
        driver.connect()
        
        # Test 1: Version check (Baseline)
        print("Sending 'v' command...")
        driver.connection.reset_input_buffer()
        res_v = driver.send_command("v'\n")
        print(f"  Response: {res_v}")
        
        # Test 2: Standard Read 'A'
        print("Sending 'A' command (Standard Read)...")
        res_a = driver.send_command("A'\n")
        print(f"  Response: {res_a}")
        
        # Test 3: Alternative Read 'R' (Just in case)
        print("Sending 'R' command (Alternative Read)...")
        res_r = driver.send_command("R'\n")
        print(f"  Response: {res_r}")
        
        # Test 4: Check for 'd' command (mentioned in legacy for Broadcom)
        print("Sending 'd' command (Broadcom check)...")
        res_d = driver.send_command("d'\n")
        print(f"  Response: {res_d}")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        driver.close()

# Run tests
test_controller("DEC", dec_sn)
test_controller("DOME", dome_sn)