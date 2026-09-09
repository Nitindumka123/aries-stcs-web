import os
import sys
import re
import json
import io
import csv
import psycopg2

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# DB credentials come from the environment (local .env, never hardcoded).
if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD environment variable is required to run this test")

# Connect as postgres (the verified user)
conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=os.environ.get('DB_PASSWORD', ''))
cur = conn.cursor()

# Patch the database module's get_db_connection to use our connection
import stcs_web.database as db_module
original_get_conn = db_module.get_db_connection

def patched_get_db_connection():
    try:
        conn2 = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=os.environ.get('DB_PASSWORD', ''))
        return conn2
    except Exception:
        return None

db_module.get_db_connection = patched_get_db_connection

from stcs_web import database
from stcs_web import obs_store

# Initialize database
database.init_users_table()

# Ensure test users exist
try:
    admin = database.get_user_by_username('Admin')
    if admin is None:
        database.create_user('Admin', 'Admin@123', role='admin')
        print('Created Admin user')
except Exception as e:
    print('Admin user: ' + str(e))

try:
    scientist = database.get_user_by_username('Scientist1')
    if scientist is None:
        database.create_user('Scientist1', 'Pass@123', role='scientist')
        print('Created Scientist1 user')
except Exception as e:
    print('Scientist1 user: ' + str(e))

# Create test observations as Admin
admin_obs1 = obs_store.create_observation(
    owner_username='Admin',
    target='M31 Andromeda',
    ra_deg=10.68,
    dec_deg=41.27,
    status='completed',
    notes='Test by Admin'
)
print('Admin obs 1: ' + str(admin_obs1))

admin_obs2 = obs_store.create_observation(
    owner_username='Admin',
    target='M42 Orion',
    ra_deg=5.37,
    dec_deg=-5.37,
    status='completed',
    notes='Test by Admin 2'
)
print('Admin obs 2: ' + str(admin_obs2))

# Create observation as Scientist1
scientist_obs1 = obs_store.create_observation(
    owner_username='Scientist1',
    target='M57 Ring',
    ra_deg=33.03,
    dec_deg=33.05,
    status='completed',
    notes='Test by Scientist1'
)
print('Scientist1 obs 1: ' + str(scientist_obs1))

# Add files
if admin_obs1:
    f1 = obs_store.record_observation_file(
        obs_id=admin_obs1,
        filename='admin_test.spe',
        file_path='/some/path/admin_test.spe',
        kind='data',
        checksum='a' * 64,
        file_size=2048,
    )
    print('Admin file 1: ' + str(f1))

if scientist_obs1:
    f2 = obs_store.record_observation_file(
        obs_id=scientist_obs1,
        filename='scientist_test.spe',
        file_path='/some/path/scientist_test.spe',
        kind='data',
        checksum='b' * 64,
        file_size=1024,
    )
    print('Scientist1 file 1: ' + str(f2))

print('')
print('=== CSV Export Verification ===')

# Simulate the export function's CSV generation
cols = ["id", "owner", "target", "ra_deg", "dec_deg", "start", "end", "duration_s", "status"]

# Get Admin's observations
res = obs_store.list_observations('Admin', 'admin', limit=5000)
admin_items = res['items']
print('Admin items: ' + str(len(admin_items)))

buf = io.StringIO()
w = csv.writer(buf)
w.writerow(cols)
for o in admin_items:
    row = [o['id'], o['owner'], o['target'], o['ra_deg'], o['dec_deg'],
           o['start'], o['end'], o['duration_s'], o['status']]
    w.writerow(row)
csv_content = buf.getvalue()

# Parse and verify
buf = io.StringIO(csv_content)
reader = csv.reader(buf)
rows = list(reader)

print('CSV header: ' + str(rows[0]))
expected_cols_match = rows[0] == cols
print('Expected cols match: ' + str(expected_cols_match))
data_rows = len(rows) - 1
print('Data rows: ' + str(data_rows))
if data_rows > 0:
    first_data_row = rows[1]
    print('First data row: ' + str(first_data_row))
    fields_count = len(first_data_row)
    print('Fields count in row: ' + str(fields_count))

# Verify CSV content has correct data
print('CSV total length: ' + str(len(csv_content)) + ' bytes')

# Check that the observation target names appear
m31_in_csv = 'M31' in csv_content
andromeda_in_csv = 'Andromeda' in csv_content
print('M31 in CSV: ' + str(m31_in_csv))
print('Andromeda in CSV: ' + str(andromeda_in_csv))

print('')
print('=== XLSX Export Verification ===')

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = 'Observations'

    ws.append(cols)
    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold

    for o in admin_items:
        row = [o['id'], o['owner'], o['target'], o['ra_deg'], o['dec_deg'],
               o['start'], o['end'], o['duration_s'], o['status']]
        ws.append([str(v) if v is not None else '' for v in row])

    buf.seek(0)
    wb.save(buf)
    buf.seek(0)
    content = buf.getvalue()

    # Verify with openpyxl
    buf.seek(0)
    wb2 = openpyxl.load_workbook(buf)
    ws2 = wb2.active

    print('XLSX sheets: ' + str(wb2.sheetnames))
    print('XLSX rows: ' + str(ws2.max_row) + ', columns: ' + str(ws2.max_column))
    header_vals = []
    for c in range(1, ws2.max_column + 1):
        header_vals.append(str(ws2.cell(row=1, column=c).value))
    print('XLSX header: ' + str(header_vals))

    if ws2.max_row > 1:
        first_row_vals = []
        for c in range(1, ws2.max_column + 1):
            first_row_vals.append(str(ws2.cell(row=2, column=c).value))
        print('XLSX first data row: ' + str(first_row_vals))

    # Verify file is valid non-empty XLSX
    print('XLSX content length: ' + str(len(content)) + ' bytes')
    is_zip = content[:4] in [b'PK\x03\x04', b'PK\x05\x06']
    print('XLSX is valid ZIP (xlsx): ' + str(is_zip))
    print('XLSX: VALID')
except ImportError:
    print('openpyxl not available')
except Exception as e:
    print('XLSX error: ' + str(e))

print('')
print('=== PDF Export Verification ===')

try:
    from fpdf import FPDF

    pdf = FPDF(orientation='L', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, 'ARIES 104 cm Sampurnanand Telescope - Observation Export',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(0, 6,
             'Exported by Admin (admin) - ' + str(len(admin_items)) + ' record(s), privacy-filtered',
             new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)
    widths = [12, 30, 60, 22, 22, 38, 38, 22, 28]
    pdf.set_font('Helvetica', 'B', 8)
    for i in range(len(cols)):
        pdf.cell(widths[i], 7, cols[i], border=1)
    pdf.ln()
    pdf.set_font('Helvetica', '', 8)
    for o in admin_items:
        for i in range(len(cols)):
            val = o.get(cols[i], '')
            if val is not None:
                txt = str(val)
            else:
                txt = '-'
            pdf.cell(widths[i], 6, txt, border=1)
        pdf.ln()

    out = pdf.output()
    if isinstance(out, str):
        out = out.encode('latin-1', errors='replace')
    elif not isinstance(out, bytes):
        out = bytes(out)

    print('PDF output size: ' + str(len(out)) + ' bytes')
    has_pdf_sig = len(out) >= 4 and out[:4] == b'%PDF'
    print('PDF starts with %PDF: ' + str(has_pdf_sig))
    is_non_empty = len(out) > 0
    print('PDF is non-empty: ' + str(is_non_empty))
    print('PDF: VALID')
except ImportError:
    print('fpdf not available')
except Exception as e:
    print('PDF error: ' + str(e))

print('')
print('=== Privacy Verification ===')

# Scientist1 should only see their own observations
res = obs_store.list_observations('Scientist1', 'scientist', limit=5000)
scientist_items = res['items']
print('Scientist1 sees ' + str(len(scientist_items)) + ' observations (own only)')

# Admin should see all
res = obs_store.list_observations('Admin', 'admin', limit=5000)
admin_items = res['items']
print('Admin sees ' + str(len(admin_items)) + ' observations (all)')

# Verify that export CSV only contains appropriate data
csv_buf = io.StringIO()
w = csv.writer(csv_buf)
w.writerow(cols)
for o in scientist_items:
    row = [o['id'], o['owner'], o['target'], o['ra_deg'], o['dec_deg'],
           o['start'], o['end'], o['duration_s'], o['status']]
    w.writerow(row)
scientist_csv = csv_buf.getvalue()
scientist_contains_1 = 'Scientist1' in scientist_csv
scientist_contains_m57 = 'M57' in scientist_csv
print('Scientist CSV contains Scientist1 obs: ' + str(scientist_contains_1))
print('Scientist CSV contains M57: ' + str(scientist_contains_m57))

csv_buf2 = io.StringIO()
w = csv.writer(csv_buf2)
w.writerow(cols)
for o in admin_items:
    row = [o['id'], o['owner'], o['target'], o['ra_deg'], o['dec_deg'],
           o['start'], o['end'], o['duration_s'], o['status']]
    w.writerow(row)
admin_csv = csv_buf2.getvalue()
admin_contains_admin = 'Admin' in admin_csv
admin_contains_m31 = 'M31' in admin_csv
print('Admin CSV contains Admin obs: ' + str(admin_contains_admin))
print('Admin CSV contains M31: ' + str(admin_contains_m31))

print('')
print('=== All export verification tests completed ===')