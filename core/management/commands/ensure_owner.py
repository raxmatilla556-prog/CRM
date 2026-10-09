import os

from django.core.management.base import BaseCommand

from core.models import User


class Command(BaseCommand):
    help = ("Bazada ega bo'lmasa, OWNER_USERNAME / OWNER_PASSWORD o'zgaruvchilaridan ega yaratadi "
            "(serverga birinchi joylashda). Ega birinchi kirishda parolni almashtiradi.")

    def handle(self, *args, **options):
        if User.objects.filter(role=User.Role.OWNER).exists():
            self.stdout.write('Ega allaqachon bor')
            return
        password = os.environ.get('OWNER_PASSWORD')
        if not password:
            self.stdout.write(self.style.WARNING("OWNER_PASSWORD berilmagan - ega yaratilmadi"))
            return
        username = os.environ.get('OWNER_USERNAME', 'ega')
        user = User(username=username, first_name='Ega', role=User.Role.OWNER,
                    is_staff=True, is_superuser=True, must_change_password=True)
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f'Ega yaratildi: {username}'))
