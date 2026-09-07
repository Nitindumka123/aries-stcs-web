import socket
import sys
from datetime import datetime

# --- CONFIGURATION ---
# In UDP Server mode, TARGET_IP is not used for binding (we bind to all IPs), 
# but it's good to know the sender's IP if you want to filter later.
TARGET_IP = '0.0.0.0' 

# The specific port the weather station is broadcasting on
TARGET_PORT = 12344 

# PROTOCOL: They are sending via UDP
PROTOCOL = 'UDP' 

# MODE: 'SERVER' 
# We must use SERVER mode to listen for incoming UDP packets on the wifi.
CONNECTION_MODE = 'SERVER'

def start_sniffer():
    print(f"--- Weather Data Sniffer Started ---")
    print(f"Listening on Port: {TARGET_PORT}")
    print(f"Protocol: {PROTOCOL} | Mode: {CONNECTION_MODE}")
    print("-" * 40)

    s = None
    try:
        if PROTOCOL == 'TCP':
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if CONNECTION_MODE == 'SERVER':
            # We listen for incoming data (Bind to our own IP or 0.0.0.0)
            bind_ip = '0.0.0.0' # Listen on all interfaces (WiFi, Ethernet, etc.)
            print(f"Binding to {bind_ip}:{TARGET_PORT} and waiting for data...")
            s.bind((bind_ip, TARGET_PORT))
            
            if PROTOCOL == 'TCP':
                s.listen(1)
                print("Waiting for connection...")
                conn, addr = s.accept()
                print(f"Connection accepted from: {addr}")
                client_sock = conn
            else:
                # UDP doesn't accept connections, we just read from 's'
                print("UDP Listener active. Waiting for packets...")
                client_sock = s
        else:
            # CLIENT mode logic (Not used for this specific UDP listener scenario)
            print(f"Attempting to connect to {TARGET_IP}:{TARGET_PORT}...")
            s.settimeout(10)
            s.connect((TARGET_IP, TARGET_PORT))
            print("Connected successfully!")
            s.settimeout(None)
            client_sock = s

        print("\nWaiting for data packets...\n")

        while True:
            # Receive data (buffer size 1024 bytes)
            if PROTOCOL == 'UDP' and CONNECTION_MODE == 'SERVER':
                # recvfrom returns the data AND the address of the sender
                data, addr = s.recvfrom(1024)
                sender_info = f"From {addr[0]}:{addr[1]}"
            else:
                data = client_sock.recv(1024)
                sender_info = ""
            
            if not data:
                print("\n[!] Connection closed or empty packet.")
                if PROTOCOL == 'TCP': break
                continue # For UDP, empty packets might just be keep-alives, keep listening
                
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            # 1. Print Raw Bytes (Hex format)
            hex_data = data.hex(' ')
            print(f"[{timestamp}] {sender_info}")
            print(f"   RAW (Hex): {hex_data}")

            # 2. Attempt to Decode (ASCII/UTF-8)
            try:
                decoded = data.decode('utf-8').strip()
                print(f"   DECODED  : {decoded}")
            except UnicodeDecodeError:
                print(f"   DECODED  : <Binary Data - Cannot Decode as Text>")

            print("-" * 20)

    except socket.timeout:
        print("\n[!] Error: Connection timed out.")
    except PermissionError:
        print(f"\n[!] Error: Permission Denied. Try running as Administrator/Sudo.")
        print(f"    Port {TARGET_PORT} might be reserved or in use.")
    except KeyboardInterrupt:
        print("\nStopping sniffer...")
    except Exception as e:
        print(f"\n[!] Error: {e}")
    finally:
        if s:
            s.close()
        print("Socket closed.")

if __name__ == "__main__":
    start_sniffer()