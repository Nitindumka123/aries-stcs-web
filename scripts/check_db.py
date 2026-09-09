import os
import psycopg2

db_password = os.environ.get('DB_PASSWORD', '')
print(f'DB_PASSWORD from env: "{db_password}"')

try:
    conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres', password=db_password)
    conn.close()
    print('DB connected with password from env')
except Exception as e:
    print(f'Failed with env password: {e}')

try:
    conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='postgres')
    conn.close()
    print('DB connected without password')
except Exception as e:
    print(f'Failed without password: {e}')

try:
    conn = psycopg2.connect(host='localhost', port=5432, dbname='stcs_observatory', user='stcs_user', password=db_password)
    conn.close()
    print('DB connected with stcs_user')
except Exception as e:
    print(f'Failed with stcs_user: {e}')