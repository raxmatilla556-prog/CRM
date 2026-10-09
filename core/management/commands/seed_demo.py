from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import User
from inventory.models import Category, Product, Supplier


class Command(BaseCommand):
    help = "Boshlang'ich foydalanuvchilar (ega, sotuvchi, omborchi) va namuna tovarlarni yaratadi"

    def handle(self, *args, **options):
        users = [
            ('ega', 'Ega', User.Role.OWNER),
            ('sotuvchi', 'Sotuvchi', User.Role.SELLER),
            ('omborchi', 'Omborchi', User.Role.WAREHOUSE),
        ]
        for username, name, role in users:
            if not User.objects.filter(username=username).exists():
                u = User(username=username, first_name=name, role=role, is_staff=role == User.Role.OWNER,
                         is_superuser=role == User.Role.OWNER)
                u.set_password('123456')
                u.must_change_password = True
                u.save()
                self.stdout.write(f'Foydalanuvchi: {username} / 123456 (birinchi kirishda parolni almashtiradi)')

        if Product.objects.exists():
            self.stdout.write('Tovarlar allaqachon bor, o\'tkazib yuborildi')
            return

        Supplier.objects.get_or_create(name='Ulgurji baza', defaults={'phone': '+998901234567'})
        cats = {n: Category.objects.get_or_create(name=n)[0] for n in ['Oziq-ovqat', 'Ichimliklar', "Ro'zg'or"]}
        demo = [
            ('Non', 'Oziq-ovqat', 'dona', 3000, 4000, 40, 0),
            ('Sut 1L', 'Oziq-ovqat', 'dona', 9000, 11000, 20, 30),
            ('Shakar', 'Oziq-ovqat', 'kg', 12000, 14000, 25, 50),
            ('Guruch', 'Oziq-ovqat', 'kg', 16000, 19000, 30, 100),
            ("Coca-Cola 1.5L", 'Ichimliklar', 'dona', 11000, 14000, 24, 48),
            ('Suv 1L', 'Ichimliklar', 'dona', 2500, 4000, 3, 60),
            ('Choy qora 100g', 'Oziq-ovqat', 'pachka', 15000, 19000, 10, 20),
            ('Kir yuvish kukuni 3kg', "Ro'zg'or", 'dona', 45000, 55000, 4, 6),
        ]
        for name, cat, unit, cost, price, store, wh in demo:
            Product.objects.create(
                name=name, category=cats[cat], unit=unit,
                cost_price=Decimal(cost), sale_price=Decimal(price),
                store_qty=Decimal(store), warehouse_qty=Decimal(wh), min_qty=Decimal(10),
            )
        self.stdout.write(self.style.SUCCESS(f'{len(demo)} ta namuna tovar yaratildi'))
