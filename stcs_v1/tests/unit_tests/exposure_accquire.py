# Import the .NET class library
import clr

# Import python sys module
import sys

# Import os module
import os

# Import System.IO for saving and opening files
from System.IO import *

# Import C compatible List and String
from System import String
from System.Collections.Generic import List
from dotenv import load_dotenv

load_dotenv()

# Add needed dll references
sys.path.append(os.environ['LIGHTFIELD_ROOT'])
sys.path.append(os.environ['LIGHTFIELD_ROOT']+"\\AddInViews")

clr.AddReference('PrincetonInstruments.LightFieldViewV5')
clr.AddReference('PrincetonInstruments.LightField.AutomationV5')
clr.AddReference('PrincetonInstruments.LightFieldAddInSupportServices')

# PI imports
from PrincetonInstruments.LightField.Automation import Automation
from PrincetonInstruments.LightField.AddIns import CameraSettings
from PrincetonInstruments.LightField.AddIns import DeviceType

def set_value(setting, value):
    # Check for existence before setting
    # gain, adc rate, or adc quality
    try:
        if 'experiment' in globals() and experiment.Exists(setting):
            experiment.SetValue(setting, value)
            print(f"Set {setting} to {value}")
        else:
            print(f"Cannot set {setting}: experiment not ready or setting missing")
    except Exception as e:
        print(f"Error setting {setting}: {e}")

def device_found():
    # Find connected device
    try:
        print("Checking devices...")
        print(f"Total devices: {len(list(experiment.ExperimentDevices))}")
        for i, device in enumerate(experiment.ExperimentDevices):
            print(f"Device {i}: Type={device.Type}, Name={getattr(device, 'DeviceName', 'N/A')}")
            if (device.Type == DeviceType.Camera):
                print("Camera found!")
                return True
        print("No camera device found.")
        return False
    except Exception as e:
        print(f"Error in device_found: {e}")
        return False

print("Starting LightField automation...")

try:
    # Create the LightField Application (true for visible)
    # The 2nd parameter forces LF to load with no experiment
    print("Launching LightField...")
    auto = Automation(True, List[String]())

    print("Automation object created. LightField should be visible now.")

    # Get experiment object
    experiment = auto.LightFieldApplication.Experiment
    print("Experiment accessed.")

    # Check devices and attempt setup
    if device_found():
        #Set exposure time
        set_value(CameraSettings.ShutterTimingExposureTime, 150.0)
        # Acquire image
        print("Starting acquisition...")
        # experiment.Acquire()
        # print("Acquire called.")
    else:
        print("Skipping acquisition due to no camera.")

    print("\nLightField launched successfully!")
    print("No auto-close: Script will keep running to hold the process open.")
    print("Press Ctrl+C to exit and close LightField cleanly.")
    print("-" * 50)

    # Keep script alive FOREVER - prevents Python exit from disposing Automation
    # LightField stays open; manual Ctrl+C needed
    while True:
        import time
        time.sleep(5)
        print("LightField still running... (no errors detected)")

except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()

finally:
    # Optional: Clean dispose on exit (Ctrl+C)
    print("Cleaning up...")
    # Note: auto.Dispose() often crashes if no hardware; commented out
    # auto.Dispose()
    input("Press Enter to fully exit...")
