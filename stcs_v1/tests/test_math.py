import sys
import os

# --- PATH FIX ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
# ----------------

from src.core.legacy_decoder import LegacyDecoder

def test_conversions():
    print("--- Testing Legacy Decoder Math ---")

    # 1. Test RA (HRA) Conversion
    # Hypothetical raw count: 10,000,000
    # Expected: (10000000 * 1.28746...) / 1000 = 12874.6 arcsec
    # Hours: 12874.6 / 54000 = 0.238 hours (~14 minutes)
    raw_ra = 10000000
    hours = LegacyDecoder.counts_to_ra_hours(raw_ra)
    hms = LegacyDecoder.decimal_hours_to_hms(hours)
    print(f"RA Raw: {raw_ra} -> Hours: {hours:.4f} -> HMS: {hms}")

    # 2. Test DEC Conversion
    # Hypothetical raw count: 4000 (Should be exactly 1 degree based on legacy comments)
    # Wait, legacy says 4000 pulses = 1 degree, so 4000 * 0.9 = 3600 arcsec = 1 degree.
    raw_dec = 4000
    degrees = LegacyDecoder.counts_to_dec_degrees(raw_dec)
    dms = LegacyDecoder.decimal_deg_to_dms(degrees)
    print(f"DEC Raw: {raw_dec} -> Degrees: {degrees:.4f} -> DMS: {dms}")
    
    # 3. Test Dome Conversion
    # Hypothetical count: 10000
    dome_az = LegacyDecoder.counts_to_dome_azimuth(10000)
    print(f"Dome Raw: 10000 -> Azimuth: {dome_az:.2f} deg")

if __name__ == "__main__":
    test_conversions()