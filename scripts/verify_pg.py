import os
import psycopg2

# DB credentials come from the environment (local .env, never hardcoded).
db_password = os.environ.get('DB_PASSWORD', '')
if not db_password:
    raise SystemExit("DB_PASSWORD environment variable is required to run this script")

# Connect to stcs_observatory and check tables
conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=db_password)
cur = conn.cursor()

# Check tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = cur.fetchall()
print('Tables in stcs_observatory:')
for t in tables:
    print(f'  {t[0]}')

# Check observation tables specifically
for table_name in ['observations', 'observation_files', 'audit_events', 'weather_readings']:
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table_name}' ORDER BY ordinal_position")
    cols = cur.fetchall()
    print(f"\nColumns in {table_name}:")
    for c in cols:
        print(f"  {c[0]} ({c[1]})")

# Check users table
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position")
cols = cur.fetchall()
print(f"\nColumns in users:")
for c in cols:
    print(f"  {c[0]} ({c[1]})")

# Check sample data
cur.execute("SELECT count(*) FROM users")
count = cur.fetchone()[0]
print(f"\nUsers count: {count}")

cur.execute("SELECT count(*) FROM observations")
count = cur.fetchone()[0]
print(f"Observations count: {count}")

cur.execute("SELECT count(*) FROM observation_files")
count = cur.fetchone()[0]
print(f"Observation files count: {count}")

cur.execute("SELECT count(*) FROM audit_events")
count = cur.fetchone()[0]
print(f"Audit events count: {count}")

# Check sample users
cur.execute("SELECT id, username, role, is_active FROM users LIMIT 5")
rows = cur.fetchall()
print(f"\nSample users:")
for r in rows:
    print(f"  id={r[0]}, username={r[1]}, role={r[2]}, is_active={r[3]}")

# Check sample observations
cur.execute("SELECT id, owner_username, target, status FROM observations LIMIT 5")
rows = cur.fetchall()
print(f"\nSample observations:")
for r in rows:
    print(f"  id={r[0]}, owner={r[1]}, target={r[2]}, status={r[3]}")

conn.close()
print("\nDone.")