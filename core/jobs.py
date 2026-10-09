"""Kunlik avtomatik vazifalar.

Vaqtlar .env da: DAILY_REPORT_TIME, DEBT_REMINDER_TIME, BACKUP_TIME (SS:DD).
`run_due_jobs()` ni tez-tez chaqirish kifoya (telegram_bot har ~30 soniyada chaqiradi) -
har bir vazifa kuniga bir marta, vaqti kelgandan keyin bajariladi. Kompyuter o'sha vaqtda
o'chiq bo'lsa, yoqilgandan keyin o'sha kuni baribir bajariladi.
"""

import logging
from datetime import time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import JobRun

logger = logging.getLogger(__name__)


def job_daily_report():
    from core.notify import send_owner
    from reports.services import daily_report_text

    return send_owner(daily_report_text())


def job_debt_reminders():
    from sales.services import customers_to_remind, send_debt_reminder

    customers = customers_to_remind(1)
    sent = sum(1 for c in customers if send_debt_reminder(c)[0])
    return True, f'{sent}/{len(customers)}'


def job_backup():
    from core.backup import make_backup
    from core.notify import owner_chat_ids, send_telegram_document

    path = make_backup()
    sent = [send_telegram_document(chat_id, path, f"💾 Zaxira nusxa: {path.name}")[0] for chat_id in owner_chat_ids()]
    return True, f'{path.name}, telegram: {sum(sent)}/{len(sent)}'


JOBS = {
    'daily_report': (job_daily_report, 'DAILY_REPORT_TIME'),
    'debt_reminders': (job_debt_reminders, 'DEBT_REMINDER_TIME'),
    'backup': (job_backup, 'BACKUP_TIME'),
}


def _parse_time(value):
    hours, minutes = value.split(':')
    return time(int(hours), int(minutes))


def run_job(name):
    func, _ = JOBS[name]
    try:
        ok, detail = func()
    except Exception as exc:
        logger.exception('Vazifa xatosi: %s', name)
        ok, detail = False, str(exc)
    return ok, str(detail)[:255]


def run_due_jobs(now=None):
    """Vaqti kelgan va bugun hali bajarilmagan vazifalarni bajaradi. Bajarilganlar ro'yxatini qaytaradi."""
    now = timezone.localtime(now)
    done = []
    for name, (_, setting) in JOBS.items():
        at = _parse_time(getattr(settings, setting))
        if now.time() < at:
            continue
        # Avval yozuv yaratamiz - ikkita jarayon bir vaqtda ishlasa ham vazifa bir marta bajariladi
        try:
            with transaction.atomic():
                run = JobRun.objects.create(name=name, run_date=now.date())
        except IntegrityError:
            continue
        ok, detail = run_job(name)
        run.success, run.detail = ok, detail
        run.save(update_fields=['success', 'detail'])
        done.append((name, ok, detail))
    return done


def schedule_info():
    today = timezone.localdate()
    runs = {r.name: r for r in JobRun.objects.filter(run_date=today)}
    return [
        {'name': name, 'time': getattr(settings, setting), 'run': runs.get(name)}
        for name, (_, setting) in JOBS.items()
    ]

