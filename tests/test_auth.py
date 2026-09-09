import os
import sys
import re

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# DB credentials come from the environment (local .env, never hardcoded).
if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD environment variable is required to run this test")

# Clear stcs_web modules
for mod in list(sys.modules.keys()):
    if 'stcs_web' in mod:
        del sys.modules[mod]

from stcs_web.main import app
from starlette.testclient import TestClient

client = TestClient(app)

# Test 1: GET login page
r = client.get('/api/login')
print('Test 1 - GET /api/login:')
print('  Status: ' + str(r.status_code))
print('  CSRF token in page: ' + str('_stcs_csrf_token' in r.text))

csrf_token = None
if '_stcs_csrf_token' in r.text:
    match = re.search(r'_stcs_csrf_token" value="([^"]+)"', r.text)
    if match:
        csrf_token = match.group(1)

# Test 2: POST login with valid credentials
if csrf_token:
    print()
    print('Test 2 - POST /api/login (Scientist1):')
    r = client.post('/api/login', data={
        'username': 'Scientist1',
        'password': 'Pass@123',
        '_stcs_csrf_token': csrf_token
    }, follow_redirects=False)
    print('  Status: ' + str(r.status_code))
    print('  Location: ' + str(r.headers.get('location', 'none')))

    # Auth check
    r = client.get('/api/auth/check')
    print()
    print('Test 3 - GET /api/auth/check:')
    print('  Status: ' + str(r.status_code))
    if r.status_code == 200:
        data = r.json()
        print('  Authenticated: ' + str(data.get('authenticated')))
        print('  Username: ' + str(data.get('username')))
        print('  Role: ' + str(data.get('role')))

    # Protected page
    r = client.get('/app/control', follow_redirects=False)
    print()
    print('Test 4 - GET /app/control (unauth):')
    print('  Status: ' + str(r.status_code))

    # Logout
    print()
    print('Test 5 - POST /api/logout:')
    r = client.post('/api/logout', follow_redirects=False)
    print('  Status: ' + str(r.status_code))

    # Auth after logout
    r = client.get('/api/auth/check')
    print()
    print('Test 6 - GET /api/auth/check after logout:')
    print('  Status: ' + str(r.status_code))
    if r.status_code == 200:
        data = r.json()
        print('  Authenticated: ' + str(data.get('authenticated')))

    # Invalid login
    print()
    print('Test 7 - POST /api/login (bad password):')
    r = client.post('/api/login', data={
        'username': 'Scientist1',
        'password': 'WrongPass',
        '_stcs_csrf_token': csrf_token
    }, follow_redirects=False)
    print('  Status: ' + str(r.status_code))

    # Unknown user
    print()
    print('Test 8 - POST /api/login (unknown user):')
    r = client.post('/api/login', data={
        'username': 'Unknown',
        'password': 'whatever',
        '_stcs_csrf_token': csrf_token
    }, follow_redirects=False)
    print('  Status: ' + str(r.status_code))

    # Scientist cannot access admin
    print()
    print('Test 9 - Scientist attempting admin:')
    r = client.get('/app/admin', follow_redirects=False)
    print('  Status: ' + str(r.status_code))

print()
print('=== Auth verification complete ===')