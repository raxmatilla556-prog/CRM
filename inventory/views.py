from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.i18n import tr
from core.models import log_action
from core.utils import fmt_money
from core.permissions import role_required, warehouse_required
from inventory.forms import CategoryForm, ProductForm, SupplierForm, TransferForm
from inventory.models import (
    Category, Location, Product, Receipt, ReceiptItem, StockCount, StockCountItem, Supplier, Transfer,
)


def _decimal(value, default=None):
    try:
        return Decimal(str(value).replace(' ', '').replace(',', '.'))
    except (InvalidOperation, TypeError, ValueError):
        return default


# ---------- Tovarlar ----------

@role_required('warehouse', 'seller')
def stock(request):
    products = Product.objects.select_related('category')
    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(name__icontains=q)
    category = request.GET.get('category')
    if category:
        products = products.filter(category_id=category)
    if request.GET.get('low'):
        products = products.filter(pk__in=Product.low_stock().values('pk'))
    if not request.GET.get('inactive'):
        products = products.filter(is_active=True)
    page = Paginator(products, 50).get_page(request.GET.get('page'))
    return render(request, 'inventory/stock.html', {
        'page': page, 'categories': Category.objects.all(), 'q': q,
        'low_count': Product.low_stock().count(),
    })


def _has_history(product):
    return (product.sale_items.exists() or product.receipt_items.exists()
            or product.transfers.exists() or StockCountItem.objects.filter(product=product).exists())


@warehouse_required
def product_edit(request, pk=None):
    instance = get_object_or_404(Product, pk=pk) if pk else None
    old = {'cost_price': instance.cost_price, 'sale_price': instance.sale_price} if instance else {}
    form = ProductForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        product = form.save()
        if instance:
            changes = [f'{label}: {fmt_money(old[f])} → {fmt_money(getattr(product, f))}'
                       for f, label in (('sale_price', 'sotuv narxi'), ('cost_price', 'tannarx'))
                       if old[f] != getattr(product, f)]
            log_action(request.user, f"Tovar tahrirlandi: {product.name}" + (f" ({'; '.join(changes)})" if changes else ''))
        else:
            log_action(request.user, f"Tovar qo‘shildi: {product.name} ({fmt_money(product.sale_price)} so‘m)")
        messages.success(request, tr('Saqlandi'))
        return redirect(request.GET.get('back') == 'receipt' and 'inventory:receipt_create' or 'inventory:stock')
    return render(request, 'inventory/product_form.html', {
        'form': form, 'instance': instance,
        'can_delete': instance is not None and not _has_history(instance),
    })


@warehouse_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if _has_history(product):
        messages.error(request, tr("Tarixi bor tovarni o'chirib bo'lmaydi. Uni nofaol qiling."))
        return redirect('inventory:product_edit', pk=pk)
    log_action(request.user, f"Tovar o'chirildi: {product.name}")
    product.delete()
    messages.success(request, tr("O'chirildi"))
    return redirect('inventory:stock')


@role_required('warehouse', 'seller')
def product_api(request):
    """Kassa va kirim sahifalari uchun tovar qidirish."""
    q = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True)
    if q:
        # Nomi qidiruvdagi so'z bilan boshlanadiganlar birinchi chiqadi
        products = sorted(products.filter(name__icontains=q)[:50],
                          key=lambda p: (not p.name.lower().startswith(q.lower()), p.name.lower()))[:20]
    else:
        products = products[:20]
    show_cost = request.user.is_owner or request.user.is_warehouse
    return JsonResponse({'results': [{
        'id': p.id, 'name': p.name, 'unit': p.unit,
        'sale_price': str(p.sale_price), 'cost_price': str(p.cost_price) if show_cost else None,
        'store_qty': str(p.store_qty), 'warehouse_qty': str(p.warehouse_qty),
    } for p in products]})


def _simple_crud(request, model, form_class, url_name, title, kind):
    """Kategoriya va yetkazib beruvchi uchun: qo'shish, tahrirlash (?edit=ID), o'chirish."""
    instance = get_object_or_404(model, pk=request.GET['edit']) if request.GET.get('edit') else None
    form = form_class(request.POST or None, instance=instance)
    if request.method == 'POST':
        if 'delete' in request.POST:
            obj = get_object_or_404(model, pk=request.POST['delete'])
            log_action(request.user, f"{title} o'chirildi: {obj}")
            obj.delete()  # bog'langan tovar/kirimlarda maydon bo'sh qoladi (SET_NULL)
            messages.success(request, tr("O'chirildi"))
            return redirect(url_name)
        if form.is_valid():
            obj = form.save()
            log_action(request.user, f"{title} {'tahrirlandi' if instance else 'qo‘shildi'}: {obj}")
            messages.success(request, tr('Saqlandi'))
            return redirect(url_name)
    return render(request, 'inventory/simple_list.html', {
        'form': form, 'items': model.objects.all(), 'title': title, 'kind': kind, 'instance': instance,
    })


@warehouse_required
def categories(request):
    return _simple_crud(request, Category, CategoryForm, 'inventory:categories', 'Kategoriyalar', 'category')


@warehouse_required
def suppliers(request):
    return _simple_crud(request, Supplier, SupplierForm, 'inventory:suppliers', 'Yetkazib beruvchilar', 'supplier')


# ---------- Kirim ----------

@warehouse_required
def receipt_list(request):
    page = Paginator(Receipt.objects.select_related('supplier', 'created_by'), 30).get_page(request.GET.get('page'))
    return render(request, 'inventory/receipt_list.html', {'page': page})


@warehouse_required
def receipt_create(request):
    errors = []
    if request.method == 'POST':
        ids = request.POST.getlist('product')
        qtys = request.POST.getlist('qty')
        costs = request.POST.getlist('cost')
        sale_prices = request.POST.getlist('sale_price')
        expiries = request.POST.getlist('expiry')
        rows = []
        for i, pid in enumerate(ids):
            if not pid:
                continue
            qty, cost = _decimal(qtys[i]), _decimal(costs[i])
            if not qty or qty <= 0 or cost is None or cost < 0:
                errors.append(tr("{n}-qator: miqdor yoki narx noto'g'ri", n=i + 1))
                continue
            rows.append((pid, qty, cost, _decimal(sale_prices[i]) if i < len(sale_prices) else None,
                         parse_date(expiries[i]) if i < len(expiries) and expiries[i] else None))
        if not rows and not errors:
            errors.append(tr("Kamida bitta tovar qo'shing"))
        if not errors:
            with transaction.atomic():
                receipt = Receipt.objects.create(
                    supplier_id=request.POST.get('supplier') or None,
                    note=request.POST.get('note', '')[:255], created_by=request.user,
                )
                total = Decimal('0')
                price_changes = []
                for pid, qty, cost, sale_price, expiry in rows:
                    product = Product.objects.select_for_update().get(pk=pid)
                    # O'rtacha tannarx (vaznli)
                    old_qty = max(product.total_qty, Decimal('0'))
                    product.cost_price = ((old_qty * product.cost_price + qty * cost) / (old_qty + qty)).quantize(Decimal('0.01'))
                    if sale_price and sale_price > 0 and sale_price != product.sale_price:
                        price_changes.append(f'{product.name}: {fmt_money(product.sale_price)} → {fmt_money(sale_price)}')
                        product.sale_price = sale_price
                    product.warehouse_qty += qty
                    product.save(update_fields=['cost_price', 'sale_price', 'warehouse_qty'])
                    ReceiptItem.objects.create(receipt=receipt, product=product, qty=qty, cost_price=cost, expiry_date=expiry)
                    total += qty * cost
                receipt.total_cost = total
                receipt.save(update_fields=['total_cost'])
            log_action(request.user, f'Kirim #{receipt.pk}: {fmt_money(total)} so‘m')
            if price_changes:
                log_action(request.user, f"Kirim #{receipt.pk}, sotuv narxi o‘zgardi: {'; '.join(price_changes)}")
            messages.success(request, tr('Kirim saqlandi'))
            return redirect('inventory:receipt_detail', pk=receipt.pk)
    return render(request, 'inventory/receipt_form.html', {'suppliers': Supplier.objects.all(), 'errors': errors})


@warehouse_required
def receipt_detail(request, pk):
    receipt = get_object_or_404(Receipt.objects.select_related('supplier', 'created_by'), pk=pk)
    return render(request, 'inventory/receipt_detail.html', {
        'receipt': receipt, 'items': receipt.items.select_related('product'),
    })


# ---------- Ko'chirish ----------

@warehouse_required
def transfer(request):
    form = TransferForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        product, qty = form.cleaned_data['product'], form.cleaned_data['qty']
        src = form.cleaned_data['from_location']
        dst = Location.STORE if src == Location.WAREHOUSE else Location.WAREHOUSE
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)
            if product.qty_at(src) < qty:
                messages.error(request, tr("Yetarli tovar yo'q"))
                return redirect('inventory:transfer')
            product.add_qty(src, -qty)
            product.add_qty(dst, qty)
            Transfer.objects.create(product=product, from_location=src, to_location=dst, qty=qty, created_by=request.user)
        log_action(request.user, f"Ko'chirish: {product.name} {qty} ({Location(src).label} → {Location(dst).label})")
        messages.success(request, tr("Ko'chirildi"))
        return redirect('inventory:transfer')
    transfers = Transfer.objects.select_related('product', 'created_by')[:50]
    return render(request, 'inventory/transfer.html', {'form': form, 'transfers': transfers})


# ---------- Inventarizatsiya ----------

@warehouse_required
def count_list(request):
    counts = StockCount.objects.select_related('created_by').prefetch_related('items')[:50]
    return render(request, 'inventory/count_list.html', {'counts': counts})


@warehouse_required
def count_create(request):
    location = request.GET.get('location') or request.POST.get('location') or Location.WAREHOUSE
    if location not in Location.values:
        location = Location.WAREHOUSE
    products = Product.objects.filter(is_active=True).select_related('category')
    if request.method == 'POST':
        with transaction.atomic():
            count = StockCount.objects.create(location=location, created_by=request.user,
                                              note=request.POST.get('note', '')[:255])
            n = 0
            for product in products.select_for_update():
                actual = _decimal(request.POST.get(f'actual_{product.pk}', ''))
                if actual is None or actual < 0:
                    continue
                system_qty = product.qty_at(location)
                StockCountItem.objects.create(count=count, product=product, system_qty=system_qty,
                                              actual_qty=actual, cost_price=product.cost_price)
                if actual != system_qty:
                    product.add_qty(location, actual - system_qty)
                n += 1
            if not n:
                transaction.set_rollback(True)
                messages.error(request, tr("Kamida bitta tovar sonini kiriting"))
                return redirect(f'{request.path}?location={location}')
        log_action(request.user, f'Inventarizatsiya #{count.pk} ({Location(location).label}), {n} ta tovar')
        messages.success(request, tr('Inventarizatsiya saqlandi'))
        return redirect('inventory:count_detail', pk=count.pk)
    return render(request, 'inventory/count_form.html', {
        'products': products, 'location': location, 'locations': Location.choices,
    })


@warehouse_required
def count_detail(request, pk):
    count = get_object_or_404(StockCount, pk=pk)
    return render(request, 'inventory/count_detail.html', {
        'count': count, 'items': count.items.select_related('product'),
    })


# ---------- Ogohlantirishlar ----------

def batch_remaining(product):
    """Tovarning har bir kirim partiyasidan qancha qolganini hisoblaydi (FIFO: eng eski partiya birinchi sotiladi).

    Hozirgi umumiy qoldiq eng yangi partiyalardan iborat deb hisoblanadi.
    {receipt_item_id: qolgan_miqdor} qaytaradi.
    """
    left = max(product.total_qty, Decimal('0'))
    result = {}
    for item in product.receipt_items.order_by('-receipt__created_at', '-pk'):
        take = min(item.qty, left)
        result[item.pk] = take
        left -= take
    return result


def expiring_items(days=None):
    """Muddati yaqin (yoki o'tgan) va haqiqatan hali sotilmagan partiyalar."""
    days = settings.EXPIRY_WARNING_DAYS if days is None else days
    today = timezone.localdate()
    items = (ReceiptItem.objects.select_related('product', 'receipt')
             .filter(expiry_date__isnull=False, expiry_date__lte=today + timedelta(days=days))
             .order_by('expiry_date'))
    remaining_cache, result = {}, []
    for item in items:
        if item.product_id not in remaining_cache:
            remaining_cache[item.product_id] = batch_remaining(item.product)
        remaining = remaining_cache[item.product_id].get(item.pk, Decimal('0'))
        if remaining > 0:
            item.remaining = remaining
            item.days_left = (item.expiry_date - today).days
            result.append(item)
    return result


@role_required('warehouse', 'seller')
def alerts(request):
    return render(request, 'inventory/alerts.html', {
        'low': Product.low_stock().select_related('category'),
        'expiring': expiring_items(),
        'days': settings.EXPIRY_WARNING_DAYS,
    })
