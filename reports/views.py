from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.notify import send_owner, telegram_configured
from core.permissions import owner_required
from inventory.models import Product
from inventory.views import expiring_items
from reports import services


@owner_required
def dashboard(request):
    period = request.GET.get('period', 'today')
    date_from, date_to = services.period_range(
        period, parse_date(request.GET.get('from', '')), parse_date(request.GET.get('to', '')),
    )
    # Grafik uchun kamida oxirgi 14 kun
    chart_from = min(date_from, date_to - services.timedelta(days=13))
    return render(request, 'reports/dashboard.html', {
        'period': period, 'date_from': date_from, 'date_to': date_to,
        's': services.summary(date_from, date_to),
        'series': services.daily_series(chart_from, date_to),
        'top': services.top_products(date_from, date_to),
        'slow': services.slow_products(date_from, date_to),
        'sellers': services.seller_stats(date_from, date_to),
        'stock_value': services.stock_value(),
        'outstanding_debt': services.outstanding_debt(),
        'low_count': Product.low_stock().count(),
        'expiring_count': len(expiring_items()),
        'telegram_ok': telegram_configured(),
        'telegram_linked': bool(request.user.telegram_chat_id),
    })


@owner_required
@require_POST
def send_report(request):
    ok, detail = send_owner(services.daily_report_text())
    if ok:
        messages.success(request, 'Hisobot yuborildi')
    else:
        messages.error(request, f'Telegram: {detail}')
    return redirect('reports:dashboard')
