import sys
import os
import time
from dotenv import load_dotenv
load_dotenv()  # Load from .env like exposure_accquire.py

# --- CONFIGURATION ---
lf_root = os.environ.get('LIGHTFIELD_ROOT', r"C:\Program Files\Princeton Instruments\LightField")

if not os.path.exists(lf_root):
    print(f"ERROR: LightField path not found: {lf_root}")
    print("Please check installation or set LIGHTFIELDROOT env variable.")
    sys.exit(1)

# --- DLL LOADING (Adapted from exposure_accquire.py) ---
try:
    import clr  # pythonnet
    print(f"--- Targeted DLL Loading from {lf_root} ---")

    # Add paths exactly as in exposure_accquire.py
    sys.path.append(lf_root)
    sys.path.append(lf_root + "\\AddInViews")

    # Explicit references (matches exposure_accquire.py exactly)
    clr.AddReference('PrincetonInstruments.LightFieldViewV5')
    clr.AddReference('PrincetonInstruments.LightField.AutomationV5')
    clr.AddReference('PrincetonInstruments.LightFieldAddInSupportServices')

    print("Targeted DLLs loaded successfully.")
except Exception as e:
    print(f"DLL Loading Error: {e}")
    sys.exit(1)

# --- IMPORT NAMESPACES ---
print("\n--- Importing Namespaces ---")
try:
    from PrincetonInstruments.LightField.Automation import Automation
    from System.Collections.Generic import List
    from System import String
    from System import Array
    print("Imports successful.")
except ImportError as e:
    print(f"Import Failed: {e}")
    sys.exit(1)

# --- CONNECTING TO LIGHTFIELD ---
print("\n--- Connecting to LightField Instance ---")
try:
    print("Attempting connection with List[String]()...")
    automation = Automation(True, List[String]())
    print("Connected to LightField Application!")

    # Get Experiment
    experiment = automation.LightFieldApplication.Experiment
    print("Experiment Loaded.")

    # Check Devices (with no-hardware safety)
    # Check Devices (Python indexing fix)
    devices = experiment.ExperimentDevices
    print(f"Found {devices.Count} Device(s).")
    if devices.Count == 0:
        print("No devices (expected without CCD).")
    else:
        for i in range(devices.Count):
            try:
                d = devices[i]  # FIXED: Use [] indexing, not .Get(i)
                print(f" - Device {i+1}: {getattr(d, 'Device', 'N/A')} ({getattr(d, 'Model', 'N/A')})")
            except Exception as dev_e:
                print(f" - Device {i+1} error: {dev_e}")

except Exception as e:
    print(f"\nFATAL ERROR during automation logic: {e}")

except ImportError:
    print("ERROR: pythonnet not installed.")
except Exception as e:
    print(f"ERROR: General Failure. {e}")

if __name__ == "__main__":
    pass
