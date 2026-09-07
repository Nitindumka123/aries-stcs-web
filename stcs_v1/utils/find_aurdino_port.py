import serial.tools.list_ports

def list_arduino_ports():
    print("Searching for connected Arduino R4 Minima boards...")
    ports = serial.tools.list_ports.comports()
    
    found_any = False
    for port in ports:
        # Check for Arduino Vendor ID (VID) generally 0x2341
        # The PID for Uno R4 Minima is typically 0x0069
        if "Arduino" in port.description or (port.vid == 0x2341):
            found_any = True
            print("-" * 40)
            print(f"Found Board on: {port.device}")
            print(f"  - Description: {port.description}")
            print(f"  - Serial Number: {port.serial_number}")
            print(f"  - Hardware ID: {port.hwid}")
            print("-" * 40)
    
    if not found_any:
        print("No Arduinos found. Make sure drivers are installed.")

if __name__ == "__main__":
    list_arduino_ports()