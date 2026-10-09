from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation

from core.i18n import current_lang


class LanguageMiddleware:
    """Har bir so'rov uchun tilni o'rnatadi (shablon, JSON javob va xabarlar uchun)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        lang = user.language if user and user.is_authenticated else request.session.get('lang', 'uz')
        lang = lang if lang in ('uz', 'ru') else 'uz'
        token = current_lang.set(lang)
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        try:
            return self.get_response(request)
        finally:
            current_lang.reset(token)
            translation.deactivate()


class ForcePasswordChangeMiddleware:
    """Vaqtinchalik (demo) parol bilan kirgan foydalanuvchini parolni almashtirishga majbur qiladi."""

    allowed = ('password_change', 'logout', 'set_language')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and user.must_change_password:
            allowed_paths = {reverse(name) for name in self.allowed}
            if request.path not in allowed_paths and not request.path.startswith('/static/'):
                return redirect('password_change')
        return self.get_response(request)


class NoIndexMiddleware:
    """Ichki sahifalar (kassa, hisobot, qarz daftari, kirish) Google qidiruviga tushmasin.

    Faqat ommaviy bosh sahifa, robots.txt va sitemap.xml indekslanadi.
    """

    public_paths = ('/', '/robots.txt', '/sitemap.xml')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path not in self.public_paths or request.user.is_authenticated:
            response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
