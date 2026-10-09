import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.forms import StyledFormMixin
from core.i18n import tr
from core.models import log_action
from core.notify import send_owner_async
from core.permissions import owner_required, seller_required
from core.utils import fmt_money
from sales.models import Customer, DebtPayment, Sale, SaleReturn, Shift
from sales.services import (
    SaleError, alert_low_stock, alert_return, can_return, create_return, create_sale, customers_with_balance,
    open_shift_for, send_debt_reminder,
)

ZERO = Decimal('0')


def _decimal(value):
    try:
        return Decimal(str(value).replace(' ', '').replace(',', '.'))
    except (InvalidOperation, TypeError, ValueError):
        return None


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'telegram_chat_id', 'note']
        labels = {'name': 'Ism', 'phone': 'Telefon', 'telegram_chat_id': 'Telegram chat ID', 'note': 'Izoh'}


def _require_shift(request):
    """Naqd pul bilan ishlash uchun ochiq smena kerak. Ega uchun ixtiyoriy."""
    shift = open_shift_for(request.user)
    if shift or request.user.is_owner:
        return shift, None
    messages.error(request, tr('Avval smenani oching'))
    return None, redirect('sales:shift')


# ---------- Smena ----------

@seller_required
def shift_view(request):
    shift = open_shift_for(request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'open' and not shift:
            opening = _decimal(request.POST.get('opening_cash') or '0')
            if opening is None or opening < 0:
                messages.error(request, tr("Summa noto'g'ri"))
                return redirect('sales:shift')
            shift = Shift.objects.create(seller=request.user, opening_cash=opening)
            log_action(request.user, f'Smena ochildi #{shift.pk}, kassada {fmt_money(opening)} so‘m')
            messages.success(request, tr('Smena ochildi'))
            return redirect('sales:pos')
        if action == 'close' and shift:
            actual = _decimal(request.POST.get('actual_cash'))
            if actual is None or actual < 0:
                messages.error(request, tr("Summa noto'g'ri"))
                return redirect('sales:shift')
            totals = shift.totals()
            shift.expected_cash = totals['expected']
            shift.actual_cash = actual
            shift.closed_at = timezone.now()
            shift.note = request.POST.get('note', '')[:255]
            shift.save()
            diff = shift.difference
            log_action(request.user, f'Smena yopildi #{shift.pk}: kutilgan {fmt_money(shift.expected_cash)}, '
                                     f'haqiqiy {fmt_money(actual)}, farq {fmt_money(diff)}')
            send_owner_async('\n'.join([
                f"🧾 <b>Smena yopildi</b> — {request.user}",
                f"Sotuvlar: {totals['sales_count']} ta, {fmt_money(totals['sales_total'])} so'm",
                f"Kutilgan naqd: {fmt_money(shift.expected_cash)}",
                f"Haqiqiy naqd: {fmt_money(actual)}",
                f"{'✅' if diff == 0 else '⚠️'} Farq: {fmt_money(diff)} so'm",
            ] + ([f"Izoh: {shift.note}"] if shift.note else [])))
            messages.success(request, tr('Smena yopildi'))
            return redirect('sales:shift_detail', pk=shift.pk)
        return redirect('sales:shift')
    return render(request, 'sales/shift.html', {
        'shift': shift, 'totals': shift.totals() if shift else None,
        'last': Shift.objects.filter(seller=request.user, closed_at__isnull=False).first(),
    })


@seller_required
def shift_detail(request, pk):
    shift = get_object_or_404(Shift.objects.select_related('seller'), pk=pk)
    if not request.user.is_owner and shift.seller_id != request.user.pk:
        return redirect('sales:shift')
    return render(request, 'sales/shift_detail.html', {'shift': shift, 'totals': shift.totals()})


@owner_required
def shift_list(request):
    shifts = Shift.objects.select_related('seller')
    page = Paginator(shifts, 50).get_page(request.GET.get('page'))
    return render(request, 'sales/shift_list.html', {'page': page})


# ---------- Kassa ----------

@seller_required
def pos(request):
    shift, redirect_response = _require_shift(request)
    if redirect_response:
        return redirect_response
    return render(request, 'sales/pos.html', {
        'default_due': timezone.localdate() + timedelta(days=14), 'shift': shift,
    })


@seller_required
@require_POST
def checkout(request):
    shift = open_shift_for(request.user)
    if not shift and not request.user.is_owner:
        return JsonResponse({'ok': False, 'error': tr('Avval smenani oching')}, status=400)
    try:
        data = json.loads(request.body)
        items = [{
            'id': int(i['id']), 'qty': _decimal(i['qty']),
            'price': _decimal(i['price']) if i.get('price') not in (None, '') else None,
        } for i in data.get('items', [])]
    except (ValueError, KeyError, TypeError, AttributeError):
        return JsonResponse({'ok': False, 'error': tr("Noto'g'ri so'rov")}, status=400)
    if any(i['qty'] is None for i in items):
        return JsonResponse({'ok': False, 'error': tr("Miqdor noto'g'ri")}, status=400)

    customer = None
    if data.get('customer_id'):
        customer = Customer.objects.filter(pk=data['customer_id']).first()
    elif (data.get('new_customer') or {}).get('name', '').strip():
        nc = data['new_customer']
        customer = Customer(name=nc['name'].strip()[:150], phone=(nc.get('phone') or '').strip()[:20])

    try:
        if customer and not customer.pk:
            customer.save()
        sale = create_sale(
            seller=request.user, items=items,
            cash=_decimal(data.get('cash')) or ZERO,
            discount=_decimal(data.get('discount')) or ZERO,
            customer=customer,
            due_date=parse_date(data.get('due_date') or ''),
            shift=shift,
        )
    except SaleError as exc:
        if customer and customer.pk and not customer.sales.exists() and data.get('new_customer'):
            customer.delete()  # sotuv bo'lmasa yangi klientni ham saqlamaymiz
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    msg = f'Sotuv #{sale.pk}: {fmt_money(sale.total)} so‘m'
    if sale.debt_amount:
        msg += f', qarzga {fmt_money(sale.debt_amount)} ({customer.name})'
    log_action(request.user, msg)
    for product, price in sale.price_changes:
        log_action(request.user, f'Sotuv #{sale.pk}: {product.name} narxi o‘zgartirildi '
                                 f'{fmt_money(product.sale_price)} → {fmt_money(price)}')
    alert_low_stock(sale.became_low)
    return JsonResponse({'ok': True, 'sale_id': sale.pk})


@seller_required
def receipt(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('seller', 'customer'), pk=pk)
    return render(request, 'sales/receipt.html', {
        'sale': sale, 'items': sale.items.select_related('product'),
        'customer_balance': sale.customer.balance if sale.customer else None,
        'autoprint': request.GET.get('print') == '1',
        'returns': sale.returns.prefetch_related('items__sale_item__product'),
        'can_return': can_return(request.user, sale),
    })


@seller_required
def sale_list(request):
    sales = Sale.objects.select_related('seller', 'customer')
    if not request.user.is_owner:
        sales = sales.filter(seller=request.user)
    date_from = parse_date(request.GET.get('from', '')) or timezone.localdate()
    date_to = parse_date(request.GET.get('to', '')) or date_from
    sales = sales.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    totals = sales.aggregate(total=Sum('total'), cash=Sum('paid_cash'), debt=Sum('debt_amount'))
    returns = SaleReturn.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    if not request.user.is_owner:
        returns = returns.filter(sale__seller=request.user)
    totals['returned'] = returns.aggregate(s=Sum('total'))['s']
    # Jami summalar JOIN siz hisoblanadi, shundan keyin har bir sotuvga qaytarilgan summa qo'shiladi
    page = Paginator(sales.annotate(returned=Sum('returns__total')), 50).get_page(request.GET.get('page'))
    for sale in page:
        sale.returnable = can_return(request.user, sale)
    return render(request, 'sales/sale_list.html', {
        'page': page, 'totals': totals, 'date_from': date_from, 'date_to': date_to,
    })


# ---------- Qarz daftari ----------

@seller_required
def debt_book(request):
    customers = customers_with_balance()
    q = request.GET.get('q', '').strip()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    show = request.GET.get('show', 'debtors')
    if show == 'debtors':
        customers = customers.filter(balance_value__gt=0)
    customers = list(customers.order_by('-balance_value'))
    today = timezone.localdate()
    for c in customers:
        c.due = c.nearest_due_date if c.balance_value > 0 else None
        c.overdue = bool(c.due and c.due < today)
    customers.sort(key=lambda c: (not c.overdue, -c.balance_value))
    total_debt = sum((c.balance_value for c in customers if c.balance_value > 0), ZERO)
    return render(request, 'sales/debt_book.html', {
        'customers': customers, 'q': q, 'show': show, 'total_debt': total_debt,
        'overdue_count': sum(1 for c in customers if c.overdue),
    })


def can_delete_payment(user, payment):
    """Ega istalgan to'lovni, sotuvchi o'zining hali yopilmagan smenadagi to'lovini o'chira oladi."""
    if user.is_owner:
        return True
    return (payment.received_by_id == user.pk and payment.shift_id is not None
            and payment.shift.closed_at is None)


@seller_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST' and request.POST.get('action') == 'pay':
        shift, redirect_response = _require_shift(request)
        if redirect_response:
            return redirect_response
        amount = _decimal(request.POST.get('amount'))
        if not amount or amount <= 0:
            messages.error(request, tr("Summa noto'g'ri"))
        elif amount > customer.balance:
            messages.error(request, tr("Summa qarzdan ko'p (qarz: {debt} so'm)", debt=fmt_money(customer.balance)))
        else:
            DebtPayment.objects.create(customer=customer, amount=amount, received_by=request.user,
                                       note=request.POST.get('note', '')[:255], shift=shift)
            log_action(request.user, f"Qarz to'lovi: {customer.name} {fmt_money(amount)} so‘m")
            messages.success(request, tr("To'lov qabul qilindi"))
        return redirect('sales:customer_detail', pk=pk)

    unpaid = customer.unpaid_sales()
    today = timezone.localdate()
    for s in unpaid:
        s.overdue = bool(s.due_date and s.due_date < today)
    payments = list(customer.payments.select_related('received_by', 'shift')[:100])
    for p in payments:
        p.deletable = can_delete_payment(request.user, p)
    return render(request, 'sales/customer_detail.html', {
        'customer': customer,
        'sales': customer.sales.select_related('seller').prefetch_related('items__product')[:100],
        'payments': payments,
        'unpaid': unpaid,
        'reminders': customer.reminders.all()[:10],
        'can_delete_customer': request.user.is_owner and not customer.sales.exists() and not payments,
    })


@seller_required
@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(DebtPayment.objects.select_related('customer', 'shift'), pk=pk)
    if not can_delete_payment(request.user, payment):
        messages.error(request, tr("Bu to'lovni o'chirishga ruxsatingiz yo'q"))
        return redirect('sales:customer_detail', pk=payment.customer_id)
    customer = payment.customer
    text = (f"To'lov o'chirildi: {customer.name} {fmt_money(payment.amount)} so‘m "
            f"({payment.created_at:%d.%m.%Y %H:%M})")
    payment.delete()
    log_action(request.user, text)
    send_owner_async(f"🗑 <b>{text}</b>\nKim: {request.user}")
    messages.success(request, tr("O'chirildi"))
    return redirect('sales:customer_detail', pk=customer.pk)


@owner_required
@require_POST
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if customer.sales.exists() or customer.payments.exists():
        messages.error(request, tr("Tarixi bor klientni o'chirib bo'lmaydi"))
        return redirect('sales:customer_detail', pk=pk)
    log_action(request.user, f"Klient o'chirildi: {customer.name}")
    customer.delete()
    messages.success(request, tr("O'chirildi"))
    return redirect('sales:debt_book')


@seller_required
@require_POST
def customer_remind(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    ok, detail = send_debt_reminder(customer)
    if ok:
        messages.success(request, tr('Eslatma yuborildi'))
        log_action(request.user, f'Qarz eslatmasi yuborildi: {customer.name}')
    else:
        messages.error(request, tr('Eslatma yuborilmadi: {detail}', detail=tr(detail)))
    return redirect('sales:customer_detail', pk=pk)


@seller_required
def customer_edit(request, pk=None):
    instance = get_object_or_404(Customer, pk=pk) if pk else None
    form = CustomerForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        customer = form.save()
        messages.success(request, tr('Saqlandi'))
        return redirect('sales:customer_detail', pk=customer.pk)
    return render(request, 'sales/customer_form.html', {'form': form, 'instance': instance})


@seller_required
def customer_api(request):
    q = request.GET.get('q', '').strip()
    customers = customers_with_balance()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    return JsonResponse({'results': [
        {'id': c.pk, 'name': c.name, 'phone': c.phone, 'balance': str(c.balance_value)}
        for c in customers[:15]
    ]})


# ---------- Vozvrat ----------

@seller_required
def sale_return(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('seller', 'customer'), pk=pk)
    if not can_return(request.user, sale):
        messages.error(request, tr("Bu sotuvni qaytarishga ruxsatingiz yo'q"))
        return redirect('sales:sale_list')
    items = list(sale.items.select_related('product'))
    for item in items:
        item.available = item.qty - item.returned_qty
    if request.method == 'POST':
        shift, redirect_response = _require_shift(request)
        if redirect_response:
            return redirect_response
        quantities = {}
        for item in items:
            qty = _decimal(request.POST.get(f'qty_{item.pk}') or '0')
            if qty is None:
                messages.error(request, tr("Miqdor noto'g'ri"))
                return redirect('sales:sale_return', pk=pk)
            if qty:
                quantities[item.pk] = qty
        try:
            ret = create_return(request.user, sale, quantities, request.POST.get('reason', ''), shift=shift)
        except SaleError as exc:
            messages.error(request, str(exc))
            return redirect('sales:sale_return', pk=pk)
        log_action(request.user, f'Vozvrat: sotuv #{sale.pk}, {fmt_money(ret.total)} so‘m')
        alert_return(ret)
        messages.success(request, tr('Vozvrat saqlandi'))
        return redirect('sales:receipt', pk=sale.pk)
    return render(request, 'sales/sale_return.html', {
        'sale': sale, 'items': items,
        'returns': sale.returns.select_related('created_by').prefetch_related('items__sale_item__product'),
    })
