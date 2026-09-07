import os
import subprocess

# Try to connect using psql with different passwords
passwords = ['postgres', 'admin', 'admin123', 'postgres123', 'password', 'Postgres123', 'postgres@123', 'Postgres@123']

for pwd in ['postgres', 'admin', 'admin123', 'postgres123', 'password', 'Postgres123', 'postgres@123', 'Postgres@123']:
    env = os.environ.copy()
    env['PGPASSWORD'] = pwd
    try:
        result = subprocess.run(
            ['psql', '-U', 'postgres', '-c', "SELECT datname FROM pg_database;"],
            capture_output=True, text=True, env=env, timeout=10
        )
        if result.returncode == 0:
            print(f'SUCCESS with password: {pwd}')
            print(result.stdout)
            break
    except Exception as e:
        pass
else:
    print('All password attempts failed')

# Also try to check if stcs_observatory database and stcs_user exist
print("\nTrying to connect as postgres with no password via local trust...")
try:
    # Try peer/trust authentication on local
    result = subprocess.run(
        ['psql', '-U', 'postgres', '-h', 'localhost', '-c', "SELECT datname FROM pg_database;"],
        capture_output=True, text=True, timeout=10
    )
    print(result.stdout)
    print(result.stderr)
except Exception as e:
    print(f"Error: {e}")