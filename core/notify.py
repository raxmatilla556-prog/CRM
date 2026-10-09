"""Telegram va Eskiz.uz SMS orqali xabar yuborish."""

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
TIMEOUT = 15


def _post(url, data, headers=None, as_json=False):
    if as_json:
        body = json.dumps(data).encode()
        headers = {**(headers or {}), 'Content-Type': 'application/json'}
    else:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method='POST')
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode() or '{}')


def telegram_configured():
    return bool(settings.TELEGRAM_BOT_TOKEN)


def send_telegram(chat_id, text):
    """Xabar yuboradi. (muvaffaqiyat, izoh) qaytaradi."""
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return False, 'Telegram sozlanmagan'
    url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage'
    try:
        data = _post(url, {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}, as_json=True)
        return bool(data.get('ok')), data.get('description', 'ok')
    except Exception as exc:  # tarmoq xatosi saytni yiqitmasligi kerak
        logger.warning('Telegram xatosi: %s', exc)
        return False, str(exc)[:200]


def send_telegram_document(chat_id, path, caption=''):
    """Faylni Telegramga yuboradi (multipart/form-data). Telegram bot limiti: 50 MB."""
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return False, 'Telegram sozlanmagan'
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (('chat_id', str(chat_id)), ('caption', caption)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    with open(path, 'rb') as f:
        content = f.read()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                  f'filename="{Path(path).name}"\r\nContent-Type: application/zip\r\n\r\n').encode())
    parts.append(content + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument', data=b''.join(parts),
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return bool(data.get('ok')), data.get('description', 'ok')
    except Exception as exc:
        logger.warning('Telegram fayl xatosi: %s', exc)
        return False, str(exc)[:200]


def owner_chat_ids():
    from core.models import User

    ids = set(User.objects.filter(role=User.Role.OWNER, is_active=True)
              .exclude(telegram_chat_id='').values_list('telegram_chat_id', flat=True))
    if settings.TELEGRAM_OWNER_CHAT_ID:
        ids.add(settings.TELEGRAM_OWNER_CHAT_ID)
    return ids


def send_owner(text):
    """Telegram ulangan barcha egalarga yuboradi. Kamida bittasiga yetib borsa muvaffaqiyat."""
    ids = owner_chat_ids()
    if not settings.TELEGRAM_BOT_TOKEN or not ids:
        return False, 'Telegram sozlanmagan'
    results = [send_telegram(chat_id, text) for chat_id in ids]
    ok = any(r[0] for r in results)
    return ok, 'ok' if ok else results[0][1]


def send_owner_async(text):
    """Egalarga fon oqimida yuboradi (sotuv tezligini sekinlashtirmaslik uchun).

    Chat ID lar shu yerda (asosiy oqimda) olinadi - fon oqimi bazaga murojaat qilmaydi.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    ids = owner_chat_ids()

    def run():
        for chat_id in ids:
            send_telegram(chat_id, text)

    threading.Thread(target=run, daemon=True).start()


def bot_username():
    """Bot @username ini Telegramdan bir marta so'rab, keshda saqlaydi."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return ''
    name = cache.get('tg_bot_username')
    if name is None:
        try:
            req = urllib.request.Request(f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe')
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                name = json.loads(resp.read().decode())['result']['username']
            cache.set('tg_bot_username', name, 60 * 60 * 24)
        except Exception as exc:
            logger.warning('getMe xatosi: %s', exc)
            return ''
    return name


def sms_configured():
    return bool(settings.ESKIZ_EMAIL and settings.ESKIZ_PASSWORD)


def _eskiz_token(force=False):
    token = None if force else cache.get('eskiz_token')
    if token:
        return token
    data = _post('https://notify.eskiz.uz/api/auth/login',
                 {'email': settings.ESKIZ_EMAIL, 'password': settings.ESKIZ_PASSWORD})
    token = data['data']['token']
    cache.set('eskiz_token', token, 60 * 60 * 24 * 25)
    return token


def normalize_phone(phone):
    digits = ''.join(ch for ch in phone or '' if ch.isdigit())
    if len(digits) == 9:
        digits = '998' + digits
    return digits if len(digits) == 12 and digits.startswith('998') else ''


def send_sms(phone, text):
    """Eskiz.uz orqali SMS. Eslatma: Eskiz matn shablonini oldindan tasdiqlatishni talab qiladi."""
    if not sms_configured():
        return False, 'SMS sozlanmagan'
    phone = normalize_phone(phone)
    if not phone:
        return False, "Telefon raqami noto'g'ri"
    payload = {'mobile_phone': phone, 'message': text, 'from': settings.ESKIZ_FROM}
    try:
        try:
            data = _post('https://notify.eskiz.uz/api/message/sms/send', payload,
                         headers={'Authorization': f'Bearer {_eskiz_token()}'})
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
            data = _post('https://notify.eskiz.uz/api/message/sms/send', payload,
                         headers={'Authorization': f'Bearer {_eskiz_token(force=True)}'})
        ok = data.get('status') in ('waiting', 'success', 'ok') or 'id' in data
        return ok, str(data.get('message') or data.get('status') or '')[:200]
    except Exception as exc:
        logger.warning('SMS xatosi: %s', exc)
        return False, str(exc)[:200]
