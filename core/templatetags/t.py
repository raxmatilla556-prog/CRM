from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

from core.i18n import translate
from core.utils import fmt_money, fmt_qty

register = template.Library()


@register.simple_tag
def t(text):
    # Faqat shablondagi o'zgarmas matnlar uchun (foydalanuvchi ma'lumoti emas), JS ichida ham ishlatiladi
    return mark_safe(translate(text))


@register.filter
def tr(text):
    return translate(text)


@register.filter
def money(value):
    return fmt_money(value)


@register.filter
def mul(a, b):
    try:
        return Decimal(a or 0) * Decimal(b or 0)
    except (InvalidOperation, TypeError, ValueError):
        return ''


@register.filter
def qty(value):
    return fmt_qty(value)
