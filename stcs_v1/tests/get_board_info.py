import serial
import serial.tools.list_ports
import time

# ==============================
# CONFIGURATION
# ==============================
BAUDRATE = 115200
TIMEOUT = 2
HANDSHAKE_CMD = "ID?\n"
EXPECTED_PREFIX = "ID:"

# (Optional) Put your known serial number here
TARGET_SERIAL_NUMBER = None
# Example:
# TARGET_SERIAL_NUMBER = "320F243558313733F09C33334B573026"


# ==============================
# LIST PORTS (DEBUG FRIENDLY)
# ==============================
def list_ports_verbose():
    ports = serial.tools.list_ports.comports()
    print("\n🔍 Available Serial Ports:\n")

    for port in ports:
        print(f"Device        : {port.device}")
        print(f"Description   : {port.description}")
        print(f"HWID          : {port.hwid}")
        print(f"VID:PID       : {port.vid}:{port.pid}")
        print(f"Manufacturer  : {port.manufacturer}")
        print(f"Serial Number : {port.serial_number}")
        print("-" * 40)

    return ports


# ==============================
# FIND BY SERIAL NUMBER (BEST)
# ==============================
def find_by_serial(serial_number):
    ports = serial.tools.list_ports.comports()

    for port in ports:
        if port.serial_number == serial_number:
            print(f"✅ Found target device on {port.device}")
            return port.device

    return None


# ==============================
# HANDSHAKE WITH DEVICE
# ==============================
def handshake(port):
    try:
        with serial.Serial(port, BAUDRATE, timeout=TIMEOUT) as ser:
            print(f"\n🔌 Connecting to {port}...")
            
            # Allow board reset (important for UNO R4)
            time.sleep(2)

            ser.reset_input_buffer()

            # Send handshake
            print("📤 Sending handshake...")
            ser.write(HANDSHAKE_CMD.encode())

            start_time = time.time()

            while time.time() - start_time < 5:
                if ser.in_waiting:
                    line = ser.readline().decode(errors='ignore').strip()
                    if line:
                        print(f"📥 Received: {line}")

                        if line.startswith(EXPECTED_PREFIX):
                            print("✅ Valid device identified")
                            return True, line

            print("⚠️ No valid response")
            return False, None

    except Exception as e:
        print(f"❌ Error on {port}: {e}")
        return False, None


# ==============================
# AUTO-DETECT DEVICE
# ==============================
def auto_detect():
    ports = serial.tools.list_ports.comports()

    print("\n🚀 Auto-detecting Arduino devices...\n")

    for port in ports:
        # Filter likely candidates (UNO R4 appears as generic USB serial)
        if "USB Serial" in port.description or port.device.startswith("COM"):
            success, response = handshake(port.device)

            if success:
                return port.device, response

    return None, None


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    list_ports_verbose()

    selected_port = None
    device_info = None

    # 1. Try serial number match
    if TARGET_SERIAL_NUMBER:
        selected_port = find_by_serial(TARGET_SERIAL_NUMBER)

    # 2. Fallback: auto-detection
    if not selected_port:
        selected_port, device_info = auto_detect()

    # 3. Final result
    if selected_port:
        print(f"\n🎯 Connected Device: {selected_port}")
        if device_info:
            print(f"📌 Device Info: {device_info}")
    else:
        print("\n❌ No valid Arduino device found.")