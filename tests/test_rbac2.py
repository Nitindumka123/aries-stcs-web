import os, sys, io, csv

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# DB credentials come from the environment (local .env, never hardcoded).
if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD environment variable is required to run this test")

# Clear all stcs_web modules
for mod in list(sys.modules.keys()):
    if 'stcs_web' in mod:
        del sys.modules[mod]

# Patch database connection
import psycopg2
from stcs_web import database as db_mod

def get_conn():
    try:
        return psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=os.environ.get('DB_PASSWORD', ''))
    except Exception:
        return None

db_mod.get_db_connection = get_conn

# NOTE: do NOT clear sys.modules here — that would discard the patch above.
from stcs_web import obs_store
from stcs_web import database as db
db.init_users_table()

# Create observations
obs1 = obs_store.create_observation(owner_username='Scientist1', target='M42', status='completed')
obs2 = obs_store.create_observation(owner_username='Scientist2', target='M57', status='completed')
obs3 = obs_store.create_observation(owner_username='Admin', target='NGC7331', status='completed')

print('=== RBAC Verification ===')

# S1 sees only own
res = obs_store.list_observations('Scientist1', 'scientist', limit=5000)
s1 = res['items']
print('S1 sees ' + str(len(s1)) + ' observations (expected 1)')

# Admin sees all
res = obs_store.list_observations('Admin', 'admin', limit=5000)
a = res['items']
print('Admin sees ' + str(len(a)) + ' observations (expected 3)')

# S2 sees only own
res = obs_store.list_observations('Scientist2', 'scientist', limit=5000)
s2 = res['items']
print('S2 sees ' + str(len(s2)) + ' observations (expected 1)')

# S1 cannot get S2's obs
obs = obs_store.get_observation_with_files(obs2, 'Scientist1', 'scientist')
print('S1 gets S2 obs detail: ' + str(obs) + ' (expected None)')

# Admin can get S2's obs
obs = obs_store.get_observation_with_files(obs2, 'Admin', 'admin')
print('Admin gets S2 obs detail: ' + str(obs is not None) + ' (expected True)')

# File download
if obs1:
    fid = obs_store.record_observation_file(obs_id=obs1, filename='test.spe', file_path='/path', kind='data', checksum='abc', file_size=1024)
    r1 = obs_store.get_file_for_download(fid, 'Scientist1', 'scientist')
    r2 = obs_store.get_file_for_download(fid, 'Scientist2', 'scientist')
    r3 = obs_store.get_file_for_download(fid, 'Admin', 'admin')
    print('S1 downloads own: ' + str(r1 is not None) + ' (expect True)')
    print('S2 downloads S1 file: ' + str(r2 is None) + ' (expect None/False)')
    print('Admin downloads any: ' + str(r3 is not None) + ' (expect True)')

# Delete
if obs1:
    r, reason = obs_store.delete_observation(obs1, 'Scientist1', 'scientist')
    print('S1 deletes own: ' + str(r) + ', ' + str(reason) + ' (expect True, Deleted)')

if obs2:
    r, reason = obs_store.delete_observation(obs2, 'Scientist1', 'scientist')
    print('S1 deletes S2 obs: ' + str(r) + ', ' + str(reason) + ' (expect False, auth error)')
    r, reason = obs_store.delete_observation(obs2, 'Admin', 'admin')
    print('Admin deletes S2: ' + str(r) + ', ' + str(reason) + ' (expect True)')

print()
print('=== RBAC verification complete ===')