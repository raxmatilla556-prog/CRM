from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.i18n import tr
from core.notify import send_sms, send_telegram
from core.utils import fmt_money, fmt_qty
from inventory.models import Location, Product
from sales.models import Customer, DebtPayment, ReminderLog, Sale, SaleItem, SaleReturn, SaleReturnItem, Shift

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=16, decimal_places=2)


class SaleError(Exception):
    pass


def customers_with_balance():
    """Klientlar ro'yxati, har biriga `debt_sum`, `paid_sum`, `balance_value` qo'shilgan."""
    debt = (Sale.objects.filter(customer=OuterRef('pk')).values('customer')
            .annotate(s=Sum('debt_amount')).values('s'))
    paid = (DebtPayment.objects.filter(customer=OuterRef('pk')).values('customer')
            .annotate(s=Sum('amount')).values('s'))
    returned = (SaleReturn.objects.filter(sale__customer=OuterRef('pk')).values('sale__customer')
                .annotate(s=Sum('debt_reduction')).values('s'))
    return Customer.objects.annotate(
        debt_sum=Coalesce(Subquery(debt, output_field=MONEY), Value(ZERO), output_field=MONEY),
        paid_sum=Coalesce(Subquery(paid, output_field=MONEY), Value(ZERO), output_field=MONEY)
        + Coalesce(Subquery(returned, output_field=MONEY), Value(ZERO), output_field=MONEY),
    ).annotate(balance_value=F('debt_sum') - F('paid_sum'))


def open_shift_for(user):
    return Shift.objects.filter(seller=user, closed_at__isnull=True).first()


def create_sale(seller, items, cash, discount=ZERO, customer=None, due_date=None, shift=None):
    """Sotuvni saqlaydi va do'kon qoldig'idan ayiradi.

    items: [{'id': product_id, 'qty': Decimal, 'price': Decimal | None}]
    'price' berilsa - kassada qo'lda o'zgartirilgan narx. Sotuvchi tannarxdan arzon sota olmaydi.
    Naqd puldan ortiq qolgan summa klient qarziga yoziladi.
    """
    if not items:
        raise SaleError(tr("Savat bo'sh"))
    with transaction.atomic():
        ids = [i['id'] for i in items]
        products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=ids, is_active=True)}
        lines, subtotal, cost_total = [], ZERO, ZERO
        for item in items:
            product = products.get(item['id'])
            qty = item['qty']
            if not product:
                raise SaleError(tr('Tovar topilmadi'))
            if qty <= 0:
                raise SaleError(tr("{name}: miqdor noto'g'ri", name=product.name))
            if product.store_qty < qty:
                raise SaleError(tr("{name}: do'konda faqat {qty} {unit} bor",
                                   name=product.name, qty=fmt_qty(product.store_qty), unit=product.unit))
            price = item.get('price')
            price = product.sale_price if price is None else price.quantize(Decimal('0.01'))
            if price <= 0:
                raise SaleError(tr("{name}: narx noto'g'ri", name=product.name))
            if price < product.cost_price and not seller.is_owner:
                raise SaleError(tr("{name}: narx tannarxdan past bo'lishi mumkin emas",
                                   name=product.name))
            lines.append((product, qty, price))
            subtotal += (qty * price).quantize(Decimal('0.01'))
            cost_total += (qty * product.cost_price).quantize(Decimal('0.01'))

        discount = min(max(discount, ZERO), subtotal)
        total = subtotal - discount
        paid = min(max(cash, ZERO), total)
        debt = total - paid
        if debt > 0 and not customer:
            raise SaleError(tr("Qarzga sotish uchun klientni tanlang"))

        sale = Sale.objects.create(
            seller=seller, customer=customer, total=total, discount=discount,
            paid_cash=paid, debt_amount=debt, due_date=due_date if debt > 0 else None,
            cost_total=cost_total, shift=shift,
        )
        SaleItem.objects.bulk_create([
            SaleItem(sale=sale, product=p, qty=q, price=price, list_price=p.sale_price, cost_price=p.cost_price)
            for p, q, price in lines
        ])
        sale.price_changes = [(p, price) for p, q, price in lines if price != p.sale_price]
        sale.became_low = []
        for product, qty, price in lines:
            was_low = product.is_low
            product.add_qty(Location.STORE, -qty)
            if not was_low and product.is_low:
                sale.became_low.append(product)
    return sale


def alert_low_stock(products):
    """Tovar minimal qoldiqdan kam bo'lib qolganda egaga Telegram xabar (fon oqimida)."""
    if not products:
        return
    from core.notify import send_owner_async

    text = '⚠️ <b>Tovar kam qoldi:</b>\n' + '\n'.join(
        f"• {p.name}: {fmt_qty(p.total_qty)} {p.unit} (do'konda {fmt_qty(p.store_qty)})" for p in products
    )
    send_owner_async(text)


def debt_reminder_text(customer):
    due = customer.nearest_due_date
    text = (f"Hurmatli {customer.name}! Sizning do'kondagi qarzingiz: "
            f"{fmt_money(customer.balance)} so'm.")
    if due:
        text += f" To'lov muddati: {due:%d.%m.%Y}."
    return text


def send_debt_reminder(customer):
    """Avval Telegram (chat ID bo'lsa), bo'lmasa SMS orqali eslatma yuboradi."""
    if customer.balance <= 0:
        return False, "Qarz yo'q"
    text = debt_reminder_text(customer)
    if customer.telegram_chat_id:
        ok, detail = send_telegram(customer.telegram_chat_id, text)
        ReminderLog.objects.create(customer=customer, channel='telegram', success=ok, detail=detail[:255])
        if ok:
            return ok, detail
    if customer.phone:
        ok, detail = send_sms(customer.phone, text)
        ReminderLog.objects.create(customer=customer, channel='sms', success=ok, detail=detail[:255])
        return ok, detail
    return False, "Klientda Telegram ham, telefon ham yo'q"


def customers_to_remind(days_before=1):
    """Muddati o'tgan yoki yaqinlashgan qarzdorlar."""
    limit = timezone.localdate() + timedelta(days=days_before)
    result = []
    for customer in customers_with_balance().filter(balance_value__gt=0):
        due = customer.nearest_due_date
        if due and due <= limit:
            result.append(customer)
    return result


def can_return(user, sale):
    """Ega istalgan sotuvni, sotuvchi faqat o'zining bugungi sotuvini qaytara oladi."""
    if user.is_owner:
        return True
    return sale.seller_id == user.pk and timezone.localtime(sale.created_at).date() == timezone.localdate()


def create_return(user, sale, quantities, reason='', shift=None):
    """Sotuvdan tovarlarni qaytaradi.

    quantities: {sale_item_id: Decimal}
    Qaytarilgan summa avval klient qarzidan ayriladi, qolgani naqd qaytariladi.
    Chegirma bo'lgan sotuvda narx chegirma ulushiga kamaytiriladi.
    """
    if not can_return(user, sale):
        raise SaleError(tr("Bu sotuvni qaytarishga ruxsatingiz yo'q"))
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale.pk)
        subtotal = sale.total + sale.discount
        factor = (sale.total / subtotal) if subtotal else Decimal('1')
        lines, total, cost_total = [], ZERO, ZERO
        for item in sale.items.select_related('product'):
            qty = quantities.get(item.pk)
            if not qty:
                continue
            if qty < 0:
                raise SaleError(tr("{name}: miqdor noto'g'ri", name=item.product.name))
            available = item.qty - item.returned_qty
            if qty > available:
                raise SaleError(tr("{name}: faqat {qty} qaytarish mumkin", name=item.product.name, qty=fmt_qty(available)))
            price = (item.price * factor).quantize(Decimal('0.01'))
            lines.append((item, qty, price))
            total += (qty * price).quantize(Decimal('0.01'))
            cost_total += (qty * item.cost_price).quantize(Decimal('0.01'))
        if not lines:
            raise SaleError(tr("Qaytariladigan tovarni tanlang"))

        debt_reduction = ZERO
        if sale.customer_id:
            debt_reduction = min(total, max(sale.customer.balance, ZERO))
        ret = SaleReturn.objects.create(
            sale=sale, created_by=user, reason=reason[:255], total=total, cost_total=cost_total,
            debt_reduction=debt_reduction, cash_refund=total - debt_reduction, shift=shift,
        )
        for item, qty, price in lines:
            SaleReturnItem.objects.create(sale_return=ret, sale_item=item, qty=qty, price=price,
                                          cost_price=item.cost_price)
            item.product.add_qty(Location.STORE, qty)
    return ret


def alert_return(ret):
    """Har bir qaytarish haqida egaga Telegram xabar (fon oqimida)."""
    from core.notify import send_owner_async

    lines = [
        f"↩️ <b>Vozvrat</b> — sotuv #{ret.sale_id}",
        f"Kim: {ret.created_by}",
        f"Summa: {fmt_money(ret.total)} so'm (naqd: {fmt_money(ret.cash_refund)}, "
        f"qarzdan: {fmt_money(ret.debt_reduction)})",
    ]
    lines += [f"• {i.sale_item.product.name} × {fmt_qty(i.qty)}" for i in ret.items.select_related('sale_item__product')]
    if ret.reason:
        lines.append(f"Sabab: {ret.reason}")
    send_owner_async('\n'.join(lines))
