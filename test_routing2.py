import subprocess
import sys
import os

# Start the server in background
proc = subprocess.Popen(
    [sys.executable, "-m", "stcs_web.main"],
    cwd=r"C:\Users\dumka\OneDrive\Desktop\GUI",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

# Give it time to start
import time
time.sleep(5)

# Now run the routing test
import requests

# Test /login page
r = requests.get('http://127.0.0.1:8000/login', allow_redirects=False)
print(f'/login: {r.status_code} -> {r.headers.get("Location", "no redirect")}')

# Test /api/login
r = requests.get('http://127.0.0.1:8000/api/login')
print(f'/api/login: {r.status_code}')

# Test root redirect
r = requests.get('http://127.0.0.1:8000/', allow_redirects=False)
print(f'/ : {r.status_code} -> {r.headers.get("Location", "no redirect")}')

# Test /app/control redirect when unauthenticated
r = requests.get('http://127.0.0.1:8000/app/control', allow_redirects=False)
print(f'/app/control (unauth): {r.status_code} -> {r.headers.get("Location", "no redirect")}')

# Test /api/login page
r = requests.get('http://127.0.0.1:8000/api/login')
has_csrf = '_stcs_csrf_token' in r.text
print(f'/api/login has CSRF: {has_csrf}')

print("ROUTING_TEST_DONE")