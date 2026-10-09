from django.conf import settings


def app_context(request):
    user = getattr(request, 'user', None)
    lang = user.language if user and user.is_authenticated else request.session.get('lang', 'uz')
    return {
        'lang': lang,
        'shop_name': settings.SHOP_NAME,
        'shop_address': settings.SHOP_ADDRESS,
        'shop_phone': settings.SHOP_PHONE,
    }
