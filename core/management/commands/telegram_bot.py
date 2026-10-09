"""Telegram botni ishga tushiradi (long polling).

- /start bosgan har kimga uning chat ID sini aytadi (ega .env ga yozib qo'yadi).
- Klient "Raqamni yuborish" tugmasini bossa, telefon raqami bo'yicha qarz daftaridagi
  klientga avtomatik bog'lanadi va keyin qarz eslatmalari Telegramga keladi.
"""

import json
import socket
import time
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.jobs import run_due_jobs
from core.models import User
from core.notify import normalize_phone, send_telegram
from sales.models import Customer

LOCK_PORT = 47652


def api(method, **params):
    url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}'
    req = urllib.request.Request(url, data=json.dumps(params).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode())


class Command(BaseCommand):
    help = 'Telegram botni ishga tushiradi'

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError('.env faylida TELEGRAM_BOT_TOKEN yo\'q')
        # Bir vaqtda faqat bitta bot ishlashi kerak (aks holda Telegram 409 Conflict qaytaradi)
        self._lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._lock.bind(('127.0.0.1', LOCK_PORT))
        except OSError:
            raise CommandError('Bot allaqachon ishlab turibdi')
        self.stdout.write(self.style.SUCCESS('Bot ishga tushdi. To\'xtatish: Ctrl+C'))
        offset = None
        while True:
            try:
                for name, ok, detail in run_due_jobs():
                    self.stdout.write(f"Vazifa {name}: {'OK' if ok else 'XATO'} {detail}")
            except Exception as exc:
                self.stderr.write(f'Vazifalar xatosi: {exc}')
            try:
                data = api('getUpdates', timeout=30, offset=offset)
            except Exception as exc:
                self.stderr.write(f'Tarmoq xatosi: {exc}')
                time.sleep(5)
                continue
            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message')
                if msg:
                    try:
                        self.handle_message(msg)
                    except Exception as exc:
                        self.stderr.write(f'Xabarni qayta ishlashda xato: {exc}')

    def handle_message(self, msg):
        chat_id = str(msg['chat']['id'])
        contact = msg.get('contact')
        if contact:
            if contact.get('user_id') != msg['from']['id']:
                send_telegram(chat_id, "Iltimos, o'zingizning raqamingizni yuboring.")
                return
            phone = normalize_phone(contact.get('phone_number'))
            matched = [c for c in Customer.objects.exclude(phone='') if normalize_phone(c.phone) == phone]
            for c in matched:
                c.telegram_chat_id = chat_id
                c.save(update_fields=['telegram_chat_id'])
            text = (f"Rahmat! Siz {settings.SHOP_NAME} klienti sifatida bog'landingiz. "
                    "Qarz eslatmalari shu yerga keladi." if matched
                    else "Bu raqam bo'yicha klient topilmadi. Do'kondagi sotuvchiga murojaat qiling.")
            api('sendMessage', chat_id=chat_id, text=text, reply_markup={'remove_keyboard': True})
            return
        text = (msg.get('text') or '').strip()
        if text.startswith('/start '):
            code = text.split(maxsplit=1)[1]
            user = User.objects.filter(telegram_link_code=code, role=User.Role.OWNER, is_active=True).first()
            if user:
                user.telegram_chat_id = chat_id
                user.telegram_link_code = ''
                user.save(update_fields=['telegram_chat_id', 'telegram_link_code'])
                api('sendMessage', chat_id=chat_id,
                    text=(f"✅ {user} — {settings.SHOP_NAME} egasi sifatida ulandingiz.\n"
                          "Kunlik hisobot va ogohlantirishlar shu yerga keladi."))
                self.stdout.write(f'Ega ulandi: {user} ({chat_id})')
                return
        api('sendMessage', chat_id=chat_id,
            text=(f"Assalomu alaykum! Bu {settings.SHOP_NAME} boti.\n"
                  f"Sizning chat ID: {chat_id}\n\n"
                  "Qarz eslatmalarini olish uchun pastdagi tugma orqali telefon raqamingizni yuboring."),
            reply_markup={'keyboard': [[{'text': '📱 Raqamni yuborish', 'request_contact': True}]],
                          'resize_keyboard': True, 'one_time_keyboard': True})
