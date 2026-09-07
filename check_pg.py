import subprocess
import os

passwords = ['postgres', 'admin', 'admin123', 'postgres123', 'password', 'Postgres123', 'postgres@123', 'Postgres@123', 'PostgreSQL', 'postgresql']

for pwd in passwords:
    env = os.environ.copy()
    env['PGPASSWORD'] = pwd
    try:
        result = subprocess.run(
            ['psql', '-U', 'postgres', '-h', 'localhost', '-p', '5432', '-c', "SELECT datname FROM pg_database;"],
            capture_output=True, text=True, env=env, timeout=10
        )
        if result.returncode == 0:
            print('SUCCESS with password:', pwd)
            print(result.stdout)
            break
    except Exception as e:
        pass
else:
    print('All password attempts failed')