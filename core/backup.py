"""Ma'lumotlar bazasining zaxira nusxasi.

Har bir nusxa - zip fayl: ichida `data.json` (har qanday bazadan tiklasa bo'ladi, `manage.py loaddata`)
va SQLite ishlatilsa baza faylining o'zi (`db.sqlite3`).
"""

import io
import sqlite3
import zipfile
from pathlib import Path

from django.conf import settings
from django.core import management
from django.db import connection
from django.utils import timezone

BACKUP_DIR = Path(settings.BASE_DIR) / 'backups'
KEEP = 30


def list_backups():
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob('backup-*.zip'), reverse=True)


def make_backup():
    """Yangi zaxira nusxa yaratadi va eskilarini (KEEP tadan ortig'ini) o'chiradi. Fayl yo'lini qaytaradi."""
    BACKUP_DIR.mkdir(exist_ok=True)
    path = BACKUP_DIR / f"backup-{timezone.localtime():%Y-%m-%d_%H-%M-%S}.zip"

    data = io.StringIO()
    management.call_command(
        'dumpdata', '--natural-foreign', '--natural-primary', '--indent', '1',
        exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'],
        stdout=data,
    )
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('data.json', data.getvalue())
        if connection.vendor == 'sqlite':
            # Ishlab turgan bazadan xavfsiz nusxa (sqlite backup API)
            db_path = settings.DATABASES['default']['NAME']
            tmp = BACKUP_DIR / '_tmp.sqlite3'
            src, dst = sqlite3.connect(db_path), sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            zf.write(tmp, 'db.sqlite3')
            tmp.unlink()

    for old in list_backups()[KEEP:]:
        old.unlink()
    return path
