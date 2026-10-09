#!/bin/sh
# Railway (yoki istalgan Linux server) uchun ishga tushirish:
# baza migratsiyasi -> statik fayllar -> ega akkaunti -> Telegram bot (fonda) -> veb-server.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput -v 0
python manage.py ensure_owner

if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  # Bot to'xtab qolsa 10 soniyadan keyin qayta ishga tushadi
  (while true; do python manage.py telegram_bot; sleep 10; done) &
fi

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 --access-logfile - --error-logfile -
