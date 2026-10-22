#!/bin/sh
set -e

echo "Waiting for database to be ready..."
python -c "
import time, sys, os
import psycopg2
from urllib.parse import urlparse

db_url = os.environ.get('DATABASE_URL', '')
if db_url:
    u = urlparse(db_url)
    for i in range(30):
        try:
            conn = psycopg2.connect(
                dbname=u.path[1:],
                user=u.username,
                password=u.password,
                host=u.hostname,
                port=u.port or 5432
            )
            conn.close()
            print('PostgreSQL is ready!')
            sys.exit(0)
        except Exception as e:
            time.sleep(1)
print('Database timeout')
sys.exit(1)
" || true

echo "Applying database migrations..."
python manage.py migrate --noinput

if [ "$SEED_DEMO" = "true" ] || [ "$SEED_DEMO" = "1" ]; then
    echo "Seeding multi-tenant demo environment..."
    python manage.py seed_enterprise_demo || true
fi

if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "true" ] || [ "$DEBUG" = "1" ]; then
    echo "Starting Django development server on 0.0.0.0:8000..."
    exec python manage.py runserver 0.0.0.0:8000
else
    echo "Starting Gunicorn production application server on 0.0.0.0:8000..."
    exec gunicorn lore_enterprise.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers ${GUNICORN_WORKERS:-4} \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
