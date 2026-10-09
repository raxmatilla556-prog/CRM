from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.utils import fmt_money as fmt, fmt_qty
from inventory.models import Product
from sales.models import DebtPayment, Sale, SaleItem, SaleReturn, SaleReturnItem
from sales.services import customers_with_balance

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=18, decimal_places=2)


def period_range(period, date_from=None, date_to=None):
    today = timezone.localdate()
    if period == 'week':
        return today - timedelta(days=6), today
    if period == 'month':
        return today.replace(day=1), today
    if period == 'year':
        return today.replace(month=1, day=1), today
    if period == 'custom' and date_from and date_to:
        return min(date_from, date_to), max(date_from, date_to)
    return today, today


def _returns(date_from, date_to):
    return SaleReturn.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)


def summary(date_from, date_to):
    """Davr ko'rsatkichlari. Vozvratlar qaytarilgan kunida daromad va foydadan ayriladi."""
    sales = Sale.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    agg = sales.aggregate(
        revenue=Sum('total'), cost=Sum('cost_total'), cash=Sum('paid_cash'),
        debt=Sum('debt_amount'), discount=Sum('discount'), count=Count('id'),
    )
    ret = _returns(date_from, date_to).aggregate(
        total=Sum('total'), cost=Sum('cost_total'), cash=Sum('cash_refund'),
    )
    returned = ret['total'] or ZERO
    revenue = (agg['revenue'] or ZERO) - returned
    count = agg['count'] or 0
    debt_paid = DebtPayment.objects.filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to,
    ).aggregate(s=Sum('amount'))['s'] or ZERO
    cash_refund = ret['cash'] or ZERO
    return {
        'revenue': revenue,
        'profit': revenue - ((agg['cost'] or ZERO) - (ret['cost'] or ZERO)),
        'count': count,
        'avg_check': (agg['revenue'] or ZERO) / count if count else ZERO,
        'cash': agg['cash'] or ZERO,
        'debt_given': agg['debt'] or ZERO,
        'debt_paid': debt_paid,
        'returned': returned,
        'cash_refund': cash_refund,
        'cash_in': (agg['cash'] or ZERO) + debt_paid - cash_refund,
        'discount': agg['discount'] or ZERO,
    }


def daily_series(date_from, date_to):
    def by_day(qs):
        rows = (qs.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
                .annotate(day=TruncDate('created_at')).values('day')
                .annotate(revenue=Sum('total'), cost=Sum('cost_total')))
        return {r['day']: r for r in rows}

    sales, returns = by_day(Sale.objects), by_day(SaleReturn.objects)
    empty = {'revenue': ZERO, 'cost': ZERO}
    result, day = [], date_from
    while day <= date_to:
        s, r = sales.get(day, empty), returns.get(day, empty)
        revenue = s['revenue'] - r['revenue']
        profit = revenue - (s['cost'] - r['cost'])
        result.append({'day': day.strftime('%d.%m'), 'revenue': float(revenue), 'profit': float(profit)})
        day += timedelta(days=1)
    return result


def top_products(date_from, date_to, limit=10):
    """Eng ko'p sotilgan tovarlar (qaytarilganlari ayirilgan holda)."""
    line_total = ExpressionWrapper(F('qty') * F('price'), output_field=MONEY)
    line_cost = ExpressionWrapper(F('qty') * F('cost_price'), output_field=MONEY)
    rows = {
        r['product_id']: r for r in
        SaleItem.objects.filter(sale__created_at__date__gte=date_from, sale__created_at__date__lte=date_to)
        .values('product_id', 'product__name', 'product__unit')
        .annotate(sold_qty=Sum('qty'), revenue=Sum(line_total), cost=Sum(line_cost))
    }
    returned = (SaleReturnItem.objects
                .filter(sale_return__created_at__date__gte=date_from, sale_return__created_at__date__lte=date_to)
                .values('sale_item__product_id')
                .annotate(q=Sum('qty'), revenue=Sum(line_total), cost=Sum(line_cost)))
    for r in returned:
        row = rows.get(r['sale_item__product_id'])
        if row:
            row['sold_qty'] -= r['q']
            row['revenue'] -= r['revenue']
            row['cost'] -= r['cost']
    result = [r for r in rows.values() if r['sold_qty'] > 0]
    for r in result:
        r['profit'] = r['revenue'] - r['cost']
    result.sort(key=lambda r: -r['revenue'])
    return result[:limit]


def slow_products(date_from, date_to, limit=10):
    """Qoldig'i bor, lekin davr ichida kam sotilgan (yoki umuman sotilmagan) tovarlar."""
    sold = dict(
        SaleItem.objects.filter(sale__created_at__date__gte=date_from, sale__created_at__date__lte=date_to)
        .values('product_id').annotate(q=Sum('qty')).values_list('product_id', 'q')
    )
    products = [p for p in Product.objects.filter(is_active=True) if p.total_qty > 0]
    for p in products:
        p.sold_qty = sold.get(p.pk, ZERO)
        p.stock_value = p.total_qty * p.cost_price
    products.sort(key=lambda p: (p.sold_qty, -p.stock_value))
    return products[:limit]


def seller_stats(date_from, date_to):
    """Sotuvchilar bo'yicha natija. Vozvratlar sotuvni qilgan sotuvchidan ayriladi."""
    rows = {
        r['seller__id']: r for r in
        Sale.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
        .values('seller__id', 'seller__username', 'seller__first_name', 'seller__last_name')
        .annotate(count=Count('id'), revenue=Sum('total'), cost=Sum('cost_total'), debt=Sum('debt_amount'))
    }
    for r in (_returns(date_from, date_to).values('sale__seller_id')
              .annotate(total=Sum('total'), cost=Sum('cost_total'))):
        row = rows.get(r['sale__seller_id'])
        if row:
            row['revenue'] -= r['total']
            row['cost'] -= r['cost']
    result = list(rows.values())
    for r in result:
        r['profit'] = r['revenue'] - r['cost']
    result.sort(key=lambda r: -r['revenue'])
    return result


def stock_value():
    total = ZERO
    for p in Product.objects.filter(is_active=True).only('store_qty', 'warehouse_qty', 'cost_price'):
        total += max(p.total_qty, ZERO) * p.cost_price
    return total


def outstanding_debt():
    return customers_with_balance().filter(balance_value__gt=0).aggregate(s=Sum('balance_value'))['s'] or ZERO


def daily_report_text(day=None):
    from inventory.views import expiring_items

    day = day or timezone.localdate()
    s = summary(day, day)
    lines = [
        f"📊 <b>Kunlik hisobot — {day:%d.%m.%Y}</b>",
        '',
        f"💰 Daromad: <b>{fmt(s['revenue'])}</b> so'm",
        f"📈 Sof foyda: <b>{fmt(s['profit'])}</b> so'm",
        f"🧾 Sotuvlar soni: {s['count']} (o'rtacha chek {fmt(s['avg_check'])})",
        f"💵 Kassaga tushgan naqd: {fmt(s['cash_in'])} so'm",
        f"📒 Qarzga berildi: {fmt(s['debt_given'])} | qaytarildi: {fmt(s['debt_paid'])}",
        f"↩️ Vozvrat: {fmt(s['returned'])} so'm (naqd {fmt(s['cash_refund'])})",
        f"📒 Umumiy qarz qoldig'i: {fmt(outstanding_debt())} so'm",
    ]
    top = top_products(day, day, 5)
    if top:
        lines += ['', '🏆 <b>Eng ko\'p sotilgan:</b>']
        lines += [f"• {t['product__name']} — {fmt(t['revenue'])} so'm" for t in top]
    low = list(Product.low_stock()[:15])
    if low:
        lines += ['', f'⚠️ <b>Kam qolgan tovarlar ({len(low)}):</b>']
        lines += [f'• {p.name}: {fmt_qty(p.total_qty)} {p.unit}' for p in low]
    expiring = expiring_items()
    if expiring:
        lines += ['', f'⏳ <b>Muddati yaqin ({len(expiring)}):</b>']
        lines += [f'• {i.product.name}: {i.expiry_date:%d.%m.%Y}' for i in expiring[:10]]
    return '\n'.join(lines)
