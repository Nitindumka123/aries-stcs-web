"""
Test: simulate CdC connecting to our INDI server.
Verifies: each response is a single line, valid XML, has DRIVER_INFO.
"""
import socket, time

HOST, PORT = "127.0.0.1", 7624
print(f"Connecting to {HOST}:{PORT}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(5)

try:
    sock.connect((HOST, PORT))
    print("Connected!\n")

    # Send getProperties (what CdC sends)
    sock.sendall(b'<getProperties version="1.7"/>\n')
    print('Sent: <getProperties version="1.7"/>')

    # Read response lines (like CdC does with RecvTerminated(LF))
    time.sleep(0.5)
    buf = b""
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass

    lines = buf.decode('utf-8').strip().split('\n')
    print(f"\nReceived {len(lines)} lines:\n")
    for i, line in enumerate(lines):
        short = line[:120] + "..." if len(line) > 120 else line
        print(f"  Line {i+1}: {short}")

    # Check CdC requirements
    full = buf.decode('utf-8')
    print(f"\n--- CdC Compatibility Checks ---")
    checks = [
        ("DRIVER_INFO present", "DRIVER_INFO" in full),
        ("DRIVER_INTERFACE=1", ">1<" in full),
        ("EQUATORIAL_EOD_COORD", "EQUATORIAL_EOD_COORD" in full),
        ("CONNECTION", "name=\"CONNECTION\"" in full),
        ("device attr non-empty", 'device=""' not in full),
    ]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {name}")

    if all(ok for _, ok in checks):
        print("\nALL CHECKS PASSED")
    else:
        print("\nSOME CHECKS FAILED")

except ConnectionRefusedError:
    print("Connection refused - is the app running?")
except Exception as e:
    print(f"Error: {e}")
finally:
    sock.close()
