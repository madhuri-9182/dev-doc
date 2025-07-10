#!/bin/bash
set -e

cd /app/git-source

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
