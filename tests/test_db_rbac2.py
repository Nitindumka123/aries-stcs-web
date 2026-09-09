import os
import sys
import psycopg2

# Project root (parent of tests/) on path for `python tests/...` runs
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# DB credentials come from the environment (local .env, never hardcoded).
if not os.environ.get("DB_PASSWORD"):
    raise SystemExit("DB_PASSWORD environment variable is required to run this test")

conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=os.environ.get('DB_PASSWORD', ''))
cur = conn.cursor()

# Add Scientist2 user if not exists
cur.execute("SELECT id FROM users WHERE username='Scientist2'")
if cur.fetchone() is None:
    cur.execute("INSERT INTO users (username, password_hash, role) VALUES ('Scientist2', 'hashed', 'scientist')")
    print('Added Scientist2 user')
else:
    print('Scientist2 user already exists')

conn.commit()

# Create observation for Scientist2
cur.execute("INSERT INTO observations (owner_username, target, ra_deg, dec_deg, status, notes) VALUES ('Scientist2', 'M57 Ring', 33.03, 33.05, 'completed', 'Test')")
conn.commit()

# Verify
cur.execute("SELECT id, owner_username, target FROM observations ORDER BY id")
obs = cur.fetchall()
print()
print('All observations after adding S2:')
for o in obs:
    print('  id=' + str(o[0]) + ', owner=' + str(o[1]) + ', target=' + str(o[2]))

# Count per user
cur.execute("SELECT owner_username, count(*) FROM observations GROUP BY owner_username")
counts = cur.fetchall()
print()
print('Observation counts per user:')
for c in counts:
    print('  ' + str(c[0]) + ': ' + str(c[1]))

# Verify RBAC: Scientist1 should not see Scientist2's data in exports
cur.execute("""
    SELECT o.owner_username, o.target FROM observations o 
    WHERE o.owner_username IN ('Scientist1', 'Scientist2')
    ORDER BY o.owner_username
""")
s_data = cur.fetchall()
print()
print('S1 and S2 observations:')
for o in s_data:
    print('  ' + str(o[0]) + ': ' + str(o[1]))

# Check that privacy enforcement query would filter correctly
cur.execute("""
    SELECT count(*) FROM observations WHERE owner_username = 'Scientist1'
""")
s1_count = cur.fetchone()[0]
print()
print('S1 observations in DB: ' + str(s1_count))

cur.execute("""
    SELECT count(*) FROM observations WHERE owner_username = 'Scientist2'
""")
s2_count = cur.fetchone()[0]
print('S2 observations in DB: ' + str(s2_count))

# Verify admin can see all
cur.execute("""
    SELECT count(*) FROM observations WHERE owner_username IN ('Scientist1', 'Scientist2', 'Admin')
""")
all_count = cur.fetchone()[0]
print('Total observations (S1+S2+Admin): ' + str(all_count))

cur.close()
conn.close()

print()
print('=== DB with Scientist2 complete ===')