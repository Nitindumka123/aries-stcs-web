import sys
import os
import time
import json
import logging
import argparse

# Add src to path so we can import Coordinator and ControlSerial
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.drivers.mount.mount_coordinator import MountCoordinator
from src.drivers.mount.control_serial import ControlSerial

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def load_settings():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'settings.json')
    with open(path, 'r') as f:
        return json.load(f)

def run_calibration(target_axes=None):
    if target_axes is None:
        target_axes = ["RA", "DEC"]
    print("STCS Motor Slip Calibration Utility")
    print("===================================\n")
    print("WARNING: This will move the telescope automatically.")
    print("Please ensure the telescope has clearance in all directions.")
    
    val = input("Proceed? (y/N): ")
    if val.lower() != 'y':
        print("Aborted.")
        return

    settings = load_settings()
    conns = settings.get("connections", {})

    # 1. Connect Encoder Coordinator (creates its own AstrometryEngine internally)
    coordinator = MountCoordinator()
    try:
        coordinator.connect_hardware()
    except Exception as e:
        print(f"Failed to connect to encoders: {e}")
        return

    # 2. Connect DUO Motor Controller
    ard_ctrl = conns.get("control_arduino", {})
    ctrl_sn = ard_ctrl.get("serial_number", "")
    ctrl_baud = ard_ctrl.get("baud_rate", 115200)

    if not ctrl_sn or ctrl_sn == "PLACEHOLDER_DUO_SERIAL_NUMBER":
        print("ERROR: Control Arduino serial number not configured in settings.json.")
        coordinator.disconnect_hardware()
        return

    control = ControlSerial(serial_number=ctrl_sn, baud_rate=ctrl_baud)
    try:
        control.connect()
    except Exception as e:
        print(f"Failed to connect to Control (DUO) motor controller: {e}")
        coordinator.disconnect_hardware()
        return

    print("\nConnected to all hardware. Waiting 2 seconds for init...")

    # ═══════════════════════════════════════════════════════════════
    # RELAY PAYLOAD BUILDER
    # ═══════════════════════════════════════════════════════════════
    # The DUO Arduino expects a 7-byte nibble payload. Each nibble's
    # individual BITS map to specific relay pins. The Arduino has a
    # WATCHDOG TIMER — if it doesn't receive a valid packet within
    # ~2 seconds, it drops ALL relays into a safety/fault state.
    # We must send heartbeat packets continuously, even when idle.
    #
    # Byte layout (from motion_state.py):
    #   [0] c_rah:  bit3=Coarse_E, bit2=Coarse_W, bit1=Fine1_E, bit0=Fine1_W
    #   [1] c_ral:  bit3=Fine2_E,  bit2=Fine2_W,  bit1=Track_ON, bit0=Track_OFF
    #   [2] c_dech: bit3=Coarse_N, bit2=Coarse_S, bit1=Fine1_N, bit0=Fine1_S
    #   [3] c_decl: bit3=Fine2_N,  bit2=Fine2_S,  bit1=(unused), bit0=(unused)
    #   [4] c_dome: bit3=CW,      bit2=CCW,      bit1=OFF,     bit0=(unused)
    #   [5] c_acc:  (accessories - unused here)
    #   [6] c_console: (reserved - unused here)
    # ═══════════════════════════════════════════════════════════════

    STOP_PAYLOAD = bytes(7)  # All zeros = all relays off

    def build_motion_payload(axis, direction, speed):
        """
        Build a correctly bit-packed 7-byte relay payload.
        
        axis: "RA" or "DEC"
        direction: 1 (East/North) or -1 (West/South) or 0 (stop)
        speed: "COARSE", "FINE_1", "FINE_2", or None (stop)
        
        Returns: bytes(7)
        """
        c_rah = 0x00
        c_ral = 0x00
        c_dech = 0x00
        c_decl = 0x00

        if direction != 0 and speed is not None:
            if axis == "RA":
                if speed == "COARSE":
                    if direction == 1:   c_rah |= 0x08  # Coarse East
                    else:                c_rah |= 0x04  # Coarse West
                elif speed == "FINE_1":
                    if direction == 1:   c_rah |= 0x02  # Fine1 East
                    else:                c_rah |= 0x01  # Fine1 West
                elif speed == "FINE_2":
                    if direction == 1:   c_ral |= 0x08  # Fine2 East
                    else:                c_ral |= 0x04  # Fine2 West
            elif axis == "DEC":
                if speed == "COARSE":
                    if direction == 1:   c_dech |= 0x08  # Coarse North
                    else:                c_dech |= 0x04  # Coarse South
                elif speed == "FINE_1":
                    if direction == 1:   c_dech |= 0x02  # Fine1 North
                    else:                c_dech |= 0x01  # Fine1 South
                elif speed == "FINE_2":
                    if direction == 1:   c_decl |= 0x08  # Fine2 North
                    else:                c_decl |= 0x04  # Fine2 South

        return bytes([c_rah, c_ral, c_dech, c_decl, 0x00, 0x00, 0x00])

    def send_packet(payload):
        """Send a relay packet using ControlSerial (includes proper encoding)."""
        control.send_relay_packet(payload)

    def active_wait(duration_sec, payload=None):
        """
        Wait for `duration_sec` while continuously sending heartbeat packets
        at 10Hz. This keeps the Arduino's watchdog fed and prevents relay
        dropout or fault-state entry.
        
        If payload is None, sends all-zeros (stop). Otherwise sends the
        given motion payload (to keep relays active during motion).
        """
        if payload is None:
            payload = STOP_PAYLOAD
        deadline = time.time() + duration_sec
        while time.time() < deadline:
            send_packet(payload)
            time.sleep(0.1)  # 10Hz heartbeat

    # ─── Prime the Arduino with heartbeat packets ───────────────
    # Send 2 seconds of all-zero heartbeats to bring the Arduino
    # out of any previous watchdog/fault state into normal operation.
    print("Priming Arduino with heartbeat (2s)...")
    active_wait(2.0)
    print("Arduino primed. Starting calibration.\n")

    try:
        def get_pos(axis):
            """Read current position from encoders via MountCoordinator.get_telemetry()."""
            telemetry = coordinator.get_telemetry()
            if axis == "RA":
                return telemetry.get("hra_decimal", 0.0) * 15.0  # HRA hours -> degrees
            else:
                return telemetry.get("dec_decimal", 0.0)

        def get_pos_with_heartbeat(axis, polls=5):
            """
            Read encoder position with heartbeat interleaved.
            Each get_telemetry() call can block for ~1s on serial timeout,
            so we send a heartbeat packet between each poll to keep the
            Arduino watchdog fed.
            """
            for _ in range(polls):
                send_packet(STOP_PAYLOAD)  # Heartbeat
                coordinator.get_telemetry()
            return get_pos(axis)

        results = {
            "RA": {"COARSE": {}, "FINE_1": {}, "FINE_2": {}},
            "DEC": {"COARSE": {}, "FINE_1": {}, "FINE_2": {}}
        }

        speeds = ["COARSE", "FINE_1", "FINE_2"]
        # VFD-adjusted timings: 5s ramp-up + 5s steady-state = 10s move
        durations = {"COARSE": 10.0, "FINE_1": 10.0, "FINE_2": 10.0}
        settle_times = {"COARSE": 6.0, "FINE_1": 6.0, "FINE_2": 6.0}
        
        # Determine which axes to calibrate
        axes_to_run = target_axes
        for axis in axes_to_run:
            print(f"\n{'='*50}")
            print(f"  Calibrating {axis} Axis")
            print(f"{'='*50}")
            for speed in speeds:
                print(f"\n  Testing Speed: {speed}")
                duration = durations[speed]
                settle = settle_times[speed]
                
                slips = []
                
                for direction in [1, -1]:
                    dir_str = ("EAST" if direction == 1 else "WEST") if axis == "RA" else ("NORTH" if direction == 1 else "SOUTH")
                    
                    print(f"\n    Direction: {dir_str}")
                
                    # ── Safety delay: active wait with all-zero heartbeat ──
                    print(f"      Safety delay (6s, with heartbeat)...")
                    active_wait(6.0)
                    
                    # ── Read start position (with heartbeat) ──
                    pos_start = get_pos_with_heartbeat(axis, polls=5)
                    
                    # ── Move for specified duration ──
                    # Build the motion payload once (it's the same every tick)
                    motion_payload = build_motion_payload(axis, direction, speed)
                    print(f"      Moving for {duration}s (payload: {motion_payload.hex()})...")
                    
                    active_wait(duration, payload=motion_payload)
                        
                    # ── Stop: send stop heartbeat ──
                    print(f"      Stopping...")
                    send_packet(STOP_PAYLOAD)
                    
                    # ── Capture position right after stop (with heartbeat) ──
                    pos_stop = get_pos_with_heartbeat(axis, polls=3)
                    
                    # ── Settle: active wait with all-zero heartbeat ──
                    print(f"      Settling ({settle}s, with heartbeat)...")
                    active_wait(settle)
                    
                    # ── Capture final settled position (with heartbeat) ──
                    pos_final = get_pos_with_heartbeat(axis, polls=5)
                    
                    # ── Calculate slip ──
                    slip = abs(pos_final - pos_stop)
                    slips.append(slip)
                    
                    total_travel = abs(pos_final - pos_start)
                    print(f"      Start: {pos_start:.4f}°, Stop Cmd: {pos_stop:.4f}°, Final: {pos_final:.4f}°")
                    print(f"      Total travel: {total_travel:.4f}°, Slip: {slip:.4f}°")

                avg_slip = sum(slips) / len(slips)
                print(f"\n    => Average Slip for {speed}: {avg_slip:.4f}°")
                
                results[axis][speed]["slip_deg"] = float(f"{avg_slip:.4f}")
                results[axis][speed]["cooldown_sec"] = float(f"{settle:.1f}")

        print(f"\n{'='*50}")
        print("  Calibration Complete!")
        print(f"{'='*50}")
        
        # Merge with existing calibration file (preserves other axis data)
        out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'slip_calibration.json')
        existing = {}
        if os.path.exists(out_path):
            try:
                with open(out_path, 'r') as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        # Update only the axes we just calibrated
        for axis in axes_to_run:
            existing[axis] = results[axis]
        
        with open(out_path, 'w') as f:
            json.dump(existing, f, indent=4)
        
        print(json.dumps(existing, indent=4))
        print(f"\nSaved to {out_path}")
        
    except KeyboardInterrupt:
        print("\n[USER ABORT] Calibration interrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] Calibration failed: {e}")
    finally:
        print("[SAFETY] Engaging emergency stop and disconnecting hardware...")
        try:
            # Send a burst of stop packets to ensure Arduino is in clean state
            for _ in range(20):
                send_packet(STOP_PAYLOAD)
                time.sleep(0.05)
        except:
            pass
        coordinator.disconnect_hardware()
        control.close()
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="STCS Motor Slip Calibration")
    parser.add_argument('--axis', choices=['RA', 'DEC', 'BOTH'], default='BOTH',
                        help='Which axis to calibrate (default: BOTH)')
    args = parser.parse_args()
    
    if args.axis == 'BOTH':
        axes = ["RA", "DEC"]
    else:
        axes = [args.axis]
    
    run_calibration(target_axes=axes)
