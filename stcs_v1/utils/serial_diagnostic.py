import sys
import os
import time
import json
import statistics

# Add src to path so we can import SmartSerial
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.drivers.mount.smart_serial import SmartSerial

def load_settings():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'settings.json')
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading settings: {e}")
        return None

def test_serial(serial_number, baudrate, num_samples=100):
    print(f"\n--- Testing Arduino SN: {serial_number} at {baudrate} baud ---")
    
    conn = SmartSerial(serial_number, baudrate)
    try:
        conn.connect()
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    print("Connected. Waiting 2 seconds for boot...")
    time.sleep(2)

    latencies = []
    successes = 0

    print(f"Sending {num_samples} commands...")
    for i in range(num_samples):
        start_t = time.perf_counter()
        # Assuming :U# is a safe benign query, like get RA. We just need ANY response.
        # If the arduino uses a specific read command like :GR# for Get RA:
        response = conn.send_command(":GR#")
        end_t = time.perf_counter()
        
        if response is not None:
            latencies.append((end_t - start_t) * 1000) # ms
            successes += 1
            sys.stdout.write(".")
        else:
            sys.stdout.write("X")
        sys.stdout.flush()
        
        time.sleep(0.05) # Don't flood it instantly
        
    conn.close()

    print("\n\nResults:")
    print(f"Success Rate: {successes}/{num_samples} ({(successes/num_samples)*100:.1f}%)")
    
    if latencies:
        print(f"Min Latency: {min(latencies):.1f} ms")
        print(f"Max Latency: {max(latencies):.1f} ms")
        print(f"Mean Latency: {statistics.mean(latencies):.1f} ms")
        
        # Calculate p95 and p99
        latencies.sort()
        idx_95 = int(len(latencies) * 0.95)
        idx_99 = int(len(latencies) * 0.99)
        # handle index bounds
        idx_95 = min(idx_95, len(latencies)-1)
        idx_99 = min(idx_99, len(latencies)-1)
        
        print(f"95th Percentile: {latencies[idx_95]:.1f} ms")
        print(f"99th Percentile: {latencies[idx_99]:.1f} ms")
        
        if max(latencies) > 50.0:
            print("WARNING: Max latency exceeds 50ms. This may cause GUI stuttering in a 10Hz loop.")
        else:
            print("Latencies look good for 10Hz polling (< 100ms budget).")

if __name__ == "__main__":
    settings = load_settings()
    if not settings:
        sys.exit(1)

    print("STCS Serial Diagnostic Tool")
    print("===========================")
    
    conns = settings.get("connections", {})
    
    # Test all controllers
    for name, config in conns.items():
        if isinstance(config, dict) and "serial_number" in config:
            # Skip science camera as it's not a serial device
            if name == "science_camera":
                continue
                
            test_serial(
                config["serial_number"], 
                config.get("baud_rate", 115200),
                num_samples=100
            )
        
    print("\nDiagnostic complete.")
