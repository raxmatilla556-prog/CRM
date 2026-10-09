from django.core.management.base import BaseCommand

from core.notify import send_owner
from reports.services import daily_report_text


class Command(BaseCommand):
    help = "Egaga Telegram orqali kunlik hisobot yuboradi (har kuni kechqurun ishga tushiring)"

    def handle(self, *args, **options):
        ok, detail = send_owner(daily_report_text())
        self.stdout.write(self.style.SUCCESS('Yuborildi') if ok else self.style.ERROR(f'Xato: {detail}'))
