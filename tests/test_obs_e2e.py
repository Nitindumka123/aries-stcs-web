import os, sys
for mod in list(sys.modules.keys()):
    if 'stcs_web' in mod:
        del sys.modules[mod]

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# DB credentials come from the environment (local .env, never hardcoded).
if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD environment variable is required to run this test")

# Patch database connection
import psycopg2
def get_conn():
    try:
        return psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=os.environ.get('DB_PASSWORD', ''))
    except Exception:
        return None

import stcs_web.database as db_mod
db_mod.get_db_connection = get_conn

# NOTE: do NOT clear sys.modules here — that would discard the patch above.
from stcs_web import obs_store
from stcs_web import database as db
db.init_users_table()

# Create observations for Scientist1 and test the full lifecycle
obs1 = obs_store.create_observation(
    owner_username='Scientist1',
    target='M42 Orion',
    ra_deg=5.37,
    dec_deg=-5.37,
    status='completed',
    notes='Test observation by S1'
)
print(f'Created observation 1: {obs1}')

obs2 = obs_store.create_observation(
    owner_username='Scientist1',
    target='M57 Ring',
    ra_deg=33.03,
    dec_deg=33.05,
    status='completed',
    notes='Test observation by S1 v2'
)
print(f'Created observation 2: {obs2}')

# Retrieve observation
res = obs_store.list_observations('Scientist1', 'scientist', limit=5000)
print(f'\nS1 list observations: {len(res["items"])} items')
for o in res['items']:
    print(f'  - {o["target"]} ({o["status"]})')

# Retrieve observation detail with files
detail = obs_store.get_observation_with_files(obs1, 'Scientist1', 'scientist')
print(f'\nS1 gets obs1 detail: success={detail is not None}')
if detail:
    print(f'  target: {detail["target"]}')
    print(f'  files: {len(detail["files"])}')

# Test privacy: Scientist1 should NOT see Admin data
res = obs_store.list_observations('Scientist1', 'scientist', limit=5000)
s1_items = res['items']
has_admin = any(o['owner'] == 'Admin' for o in s1_items)
print(f'\nS1 sees Admin data: {has_admin} (expected False)')

# Test export shape - CSV rows built from the same list_observations data
# the real /api/history/export route serves (full format coverage lives in
# tests/test_export_full.py; the old export_observations_csv helper no longer exists).
import io, csv
cols = ["id", "owner", "target", "ra_deg", "dec_deg", "status"]
for _user, _role in (('Scientist1', 'scientist'), ('Admin', 'admin')):
    _items = obs_store.list_observations(_user, _role, limit=5000)['items']
    _buf = io.StringIO()
    _w = csv.writer(_buf)
    _w.writerow(cols)
    for _o in _items:
        _w.writerow([_o['id'], _o['owner'], _o['target'],
                     _o['ra_deg'], _o['dec_deg'], _o['status']])
    _rows = list(csv.reader(io.StringIO(_buf.getvalue())))
    print(f'CSV-shape export by {_user}: {len(_rows) - 1} data rows '
          f'for {len(_items)} visible items')

# Test file download authorization
if obs1:
    fid = obs_store.record_observation_file(
        obs_id=obs1,
        filename='test.spe',
        file_path='/path/test.spe',
        kind='data',
        checksum='abc123',
        file_size=1024,
    )
    # S1 downloads own
    r1 = obs_store.get_file_for_download(fid, 'Scientist1', 'scientist')
    print(f'\nS1 downloads own file: {r1 is not None} (expected True)')
    # Admin downloads any
    rA = obs_store.get_file_for_download(fid, 'Admin', 'admin')
    print(f'Admin downloads any file: {rA is not None} (expected True)')

print('\n=== Observation archive E2E complete ===')