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
from System import Int32
load_dotenv()

# -------------------------------------------------------------------------
# Add needed DLL references
# -------------------------------------------------------------------------
sys.path.append(os.environ['LIGHTFIELD_ROOT'])
sys.path.append(os.environ['LIGHTFIELD_ROOT'] + "\\AddInViews")

clr.AddReference('PrincetonInstruments.LightFieldViewV5')
clr.AddReference('PrincetonInstruments.LightField.AutomationV5')
clr.AddReference('PrincetonInstruments.LightFieldAddInSupportServices')

# -------------------------------------------------------------------------
# Princeton Instruments imports
# -------------------------------------------------------------------------
from PrincetonInstruments.LightField.Automation import Automation
from PrincetonInstruments.LightField.AddIns import CameraSettings
from PrincetonInstruments.LightField.AddIns import DeviceType

# -------------------------------------------------------------------------
# Utility Functions
# -------------------------------------------------------------------------
def device_found():
    """Check whether a camera device is connected"""
    try:
        print("Checking devices...")
        devices = list(experiment.ExperimentDevices)
        print(f"Total devices found: {len(devices)}")

        for idx, device in enumerate(devices):
            print(f"Device {idx}: Type={device.Type}, Name={getattr(device, 'DeviceName', 'N/A')}")
            if device.Type == DeviceType.Camera:
                print("Camera detected.")
                return True

        print("No camera device detected.")
        return False

    except Exception as e:
        print(f"Error during device detection: {e}")
        return False


# def set_adc_bit_depth(bit_depth):
#     try:
#         if not experiment.Exists(CameraSettings.AdcBitDepth):
#             print("ADC Bit Depth setting not supported by this camera.")
#             return

#         clr_value = Int32(bit_depth)   # <-- CRITICAL LINE

#         # experiment.SetValue(CameraSettings.AdcBitDepth, clr_value)
#         print(f"ADC Bit Depth set to {bit_depth} bits")

#         # Optional verification
#         current = experiment.GetValue(CameraSettings.AdcBitDepth)
#         print(f"Verified ADC Bit Depth: {current}")

#     except Exception as e:
#         print(f"Failed to set ADC Bit Depth to {bit_depth}: {e}")


def get_adc_bit_depth():
    try:
        if not experiment.Exists(CameraSettings.AdcBitDepth):
            print("ADC Bit Depth setting not supported by this camera.")
            return

        current = experiment.GetValue(CameraSettings.AdcBitDepth)
        print(f"Verified ADC Bit Depth: {current}")

    except Exception as e:
        print(f"Failed to get ADC Bit Depth: {e}")

# -------------------------------------------------------------------------
# Main Execution
# -------------------------------------------------------------------------
print("Starting LightField automation...")

try:
    print("Launching LightField...")
    auto = Automation(True, List[String]())
    print("LightField launched successfully.")

    experiment = auto.LightFieldApplication.Experiment
    print("Experiment object acquired.")

    if device_found():
        # -------------------------------------------------------------
        # SET ADC BIT DEPTH HERE
        # -------------------------------------------------------------
        # set_adc_bit_depth(16)
        get_adc_bit_depth()
        print("Ready for acquisition.")
        # experiment.Acquire()

    else:
        print("Camera not available. Skipping configuration.")

    print("\nLightField is running.")
    print("Press Ctrl+C to terminate the script.")
    print("-" * 60)

    # Keep the script alive to prevent Automation disposal
    while True:
        import time
        time.sleep(5)
        print("LightField still running...")

except KeyboardInterrupt:
    print("\nUser interrupted execution.")

except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("Cleanup initiated.")
    # auto.Dispose()  # Often unsafe if hardware is disconnected
    input("Press Enter to exit completely...")
