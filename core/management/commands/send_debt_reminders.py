from django.core.management.base import BaseCommand

from sales.services import customers_to_remind, send_debt_reminder


class Command(BaseCommand):
    help = "Muddati o'tgan/yaqinlashgan qarzdorlarga Telegram yoki SMS eslatma yuboradi"

    def add_arguments(self, parser):
        parser.add_argument('--days-before', type=int, default=1, help='Muddatdan necha kun oldin eslatish')

    def handle(self, *args, **options):
        customers = customers_to_remind(options['days_before'])
        sent = 0
        for customer in customers:
            ok, detail = send_debt_reminder(customer)
            sent += ok
            self.stdout.write(f"{customer.name}: {'OK' if ok else detail}")
        self.stdout.write(self.style.SUCCESS(f'{sent}/{len(customers)} ta eslatma yuborildi'))
