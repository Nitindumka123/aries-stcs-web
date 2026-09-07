import os
import sys
import platform

print("="*60)
print("LIGHTFIELD DIAGNOSTIC TOOL")
print("="*60)

# 1. Check Architecture
bitness = platform.architecture()[0]
print(f"[INFO] Python Architecture: {bitness}")
if "64" not in bitness:
    print("[FAIL] CRITICAL: You are running 32-bit Python.")
    print("       LightField automation requires 64-bit Python to load the DLLs.")
    print("       Please reinstall Python 64-bit.")
else:
    print("[PASS] Architecture is 64-bit.")

print("-" * 60)

# 2. Check Paths
lf_root = os.environ.get('LIGHTFIELD_ROOT', r"C:\Program Files\Princeton Instruments\LightField")
print(f"[INFO] Checking LightField Root: {lf_root}")

if os.path.exists(lf_root):
    print("[PASS] LightField directory found.")
else:
    print(f"[FAIL] Directory NOT FOUND at {lf_root}")
    print("       Set LIGHTFIELD_ROOT environment variable to the correct path.")
    sys.exit(1)

print("-" * 60)

# 3. Check DLLs
dlls_to_check = [
    "PrincetonInstruments.LightFieldViewV5.dll",
    "PrincetonInstruments.LightField.AutomationV5.dll",
    "PrincetonInstruments.LightFieldAddInSupportServices.dll"
]

all_dlls_found = True
for dll in dlls_to_check:
    path = os.path.join(lf_root, dll)
    if os.path.exists(path):
        print(f"[PASS] Found: {dll}")
    else:
        print(f"[FAIL] MISSING: {dll}")
        all_dlls_found = False

if not all_dlls_found:
    print("\n[WARN] Some DLLs are missing. Check version numbers (e.g., V4, V6).")
    print("       Listing all DLLs in root folder for reference:")
    try:
        files = [f for f in os.listdir(lf_root) if f.endswith(".dll") and "Automation" in f]
        for f in files:
            print(f"       - {f}")
    except:
        pass

print("-" * 60)

# 4. Attempt CLR Load
print("[INFO] Attempting to load pythonnet (clr)...")
try:
    import clr
    print("[PASS] pythonnet is installed.")
    
    sys.path.append(lf_root)
    sys.path.append(os.path.join(lf_root, "AddInViews"))
    
    print("[INFO] Adding References...")
    try:
        clr.AddReference('PrincetonInstruments.LightField.AutomationV5')
        print("[PASS] Successfully loaded LightField Automation DLL.")
        
        from PrincetonInstruments.LightField.Automation import Automation
        print("[PASS] Successfully imported Automation class.")
        
    except Exception as e:
        print(f"[FAIL] Failed to AddReference: {e}")
        
except ImportError:
    print("[FAIL] pythonnet not installed. Run 'pip install pythonnet'")
except Exception as e:w
    print(f"[FAIL] Unexpected error: {e}")

print("="*60)
print("DIAGNOSTIC COMPLETE")