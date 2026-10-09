from django.core.management.base import BaseCommand

from core.jobs import JOBS, run_due_jobs, run_job


class Command(BaseCommand):
    help = ("Vaqti kelgan kunlik vazifalarni bajaradi (hisobot, qarz eslatmasi, zaxira). "
            "telegram_bot ishlab tursa, bu avtomatik bajariladi. --now NOM bilan darhol bajarish mumkin.")

    def add_arguments(self, parser):
        parser.add_argument('--now', choices=list(JOBS), help='Vazifani vaqtidan qat\'i nazar darhol bajarish')

    def handle(self, *args, **options):
        if options['now']:
            ok, detail = run_job(options['now'])
            self.stdout.write(f"{options['now']}: {'OK' if ok else 'XATO'} {detail}")
            return
        done = run_due_jobs()
        for name, ok, detail in done:
            self.stdout.write(f"{name}: {'OK' if ok else 'XATO'} {detail}")
        if not done:
            self.stdout.write('Bajariladigan vazifa yo\'q')
