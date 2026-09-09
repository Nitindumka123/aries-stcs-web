import os
import re
import sys

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ['WEB_RELOAD'] = '0'
os.environ['WEB_HOST'] = '127.0.0.1'
os.environ['SESSION_SECRET'] = 'test-secret-12345'
os.environ['SESSION_SECURE_COOKIE'] = 'false'

from fastapi.testclient import TestClient
from stcs_web.main import app

# Create a test client
client = TestClient(app)

# Test 1: Get login page (should create session)
r = client.get('/api/login')
print(f'GET /api/login status: {r.status_code}')
print(f'Session cookies after GET: {dict(client.cookies)}')

# Test 2: Login as Scientist1
csrf_token = None
if '_stcs_csrf_token' in r.text:
    match = re.search(r'_stcs_csrf_token" value="([^"]+)"', r.text)
    if match:
        csrf_token = match.group(1)
        print(f'CSRF token found: {csrf_token[:20]}...')

if csrf_token:
    r = client.post('/api/login', data={
        'username': 'Scientist1',
        'password': 'Pass@123',
        '_stcs_csrf_token': csrf_token
    }, follow_redirects=False)
    print(f'POST /api/login status: {r.status_code}')
    print(f'Redirect location: {r.headers.get("location", "none")}')
    
    # Test 3: Verify session persists - check auth/check
    r = client.get('/api/auth/check')
    print(f'GET /api/auth/check status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'Auth check result: {data}')
    
    # Test 4: Logout
    r = client.post('/api/logout', follow_redirects=False)
    print(f'POST /api/logout status: {r.status_code}')
    
    # Test 5: Verify session invalidated after logout
    r = client.get('/api/auth/check')
    print(f'GET /api/auth/check after logout status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'Auth check after logout: {data}')
    
    print('\nSession middleware tests completed!')
else:
    print('CSRF token not found, skipping login test')