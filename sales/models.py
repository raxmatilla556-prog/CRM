from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from inventory.models import Product


class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    telegram_chat_id = models.CharField(
        max_length=32, blank=True,
        help_text="Klient botga /start bosgandan keyin chat ID shu yerga yoziladi",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.phone})' if self.phone else self.name

    @property
    def total_debt(self):
        return self.sales.aggregate(s=Sum('debt_amount'))['s'] or Decimal('0')

    @property
    def total_paid(self):
        """Qarzni yopgan summalar: to'lovlar + qaytarilgan tovar hisobidan kamaytirilgan qarz."""
        paid = self.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        returned = SaleReturn.objects.filter(sale__customer=self).aggregate(s=Sum('debt_reduction'))['s']
        return paid + (returned or Decimal('0'))

    @property
    def balance(self):
        """Hozirgi qarz qoldig'i."""
        return self.total_debt - self.total_paid

    def unpaid_sales(self):
        """To'lovlarni eng eski qarzdan boshlab yopadi (FIFO) va to'lanmagan sotuvlarni qaytaradi.

        Har bir sotuvga `remaining` atributi qo'shiladi.
        """
        paid = self.total_paid
        result = []
        for sale in self.sales.filter(debt_amount__gt=0).order_by('created_at'):
            if paid >= sale.debt_amount:
                paid -= sale.debt_amount
                continue
            sale.remaining = sale.debt_amount - paid
            paid = Decimal('0')
            result.append(sale)
        return result

    @property
    def nearest_due_date(self):
        dates = [s.due_date for s in self.unpaid_sales() if s.due_date]
        return min(dates) if dates else None

    @property
    def is_overdue(self):
        due = self.nearest_due_date
        return bool(due and due < timezone.localdate())


class Shift(models.Model):
    """Kassa smenasi: sotuvchi ochadi, kun oxirida kassadagi naqd pulni sanab yopadi."""

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='shifts')
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_cash = models.DecimalField("Boshlang'ich naqd", max_digits=16, decimal_places=2, default=0)
    expected_cash = models.DecimalField('Kutilgan naqd', max_digits=16, decimal_places=2, null=True, blank=True)
    actual_cash = models.DecimalField('Haqiqiy naqd', max_digits=16, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-opened_at']

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def difference(self):
        if self.actual_cash is None or self.expected_cash is None:
            return None
        return self.actual_cash - self.expected_cash

    def totals(self):
        """Smena davomidagi naqd harakatlari."""
        zero = Decimal('0')
        sales = self.sales.aggregate(cash=Sum('paid_cash'), total=Sum('total'), debt=Sum('debt_amount'))
        payments = self.payments.aggregate(s=Sum('amount'))['s'] or zero
        refunds = self.returns.aggregate(s=Sum('cash_refund'))['s'] or zero
        cash_sales = sales['cash'] or zero
        return {
            'sales_total': sales['total'] or zero,
            'sales_cash': cash_sales,
            'sales_debt': sales['debt'] or zero,
            'debt_payments': payments,
            'cash_refunds': refunds,
            'sales_count': self.sales.count(),
            'expected': self.opening_cash + cash_sales + payments - refunds,
        }


class Sale(models.Model):
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='sales')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, related_name='sales')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid_cash = models.DecimalField("Naqd to'langan", max_digits=16, decimal_places=2, default=0)
    debt_amount = models.DecimalField('Qarzga yozilgan', max_digits=16, decimal_places=2, default=0)
    due_date = models.DateField("Qarz to'lov muddati", null=True, blank=True)
    cost_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, null=True, blank=True, related_name='sales')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Sotuv #{self.pk}'

    @property
    def profit(self):
        return self.total - self.cost_total


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    price = models.DecimalField(max_digits=14, decimal_places=2)
    list_price = models.DecimalField('Asl narx', max_digits=14, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2)

    @property
    def total(self):
        return self.qty * self.price

    @property
    def price_changed(self):
        return bool(self.list_price) and self.price != self.list_price

    @property
    def returned_qty(self):
        return self.returns.aggregate(s=Sum('qty'))['s'] or Decimal('0')


class SaleReturn(models.Model):
    """Sotilgan tovarni qaytarish (vozvrat)."""

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='returns')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cash_refund = models.DecimalField("Naqd qaytarilgan", max_digits=16, decimal_places=2, default=0)
    debt_reduction = models.DecimalField('Qarzdan ayrilgan', max_digits=16, decimal_places=2, default=0)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, null=True, blank=True, related_name='returns')

    class Meta:
        ordering = ['-created_at']


class SaleReturnItem(models.Model):
    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name='items')
    sale_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name='returns')
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    price = models.DecimalField(max_digits=14, decimal_places=2)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2)


class DebtPayment(models.Model):
    """Qarzdor klientning qarzini (to'liq yoki qisman) to'lashi."""

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')

    class Meta:
        ordering = ['-created_at']


class ReminderLog(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='reminders')
    channel = models.CharField(max_length=10)  # sms / telegram
    success = models.BooleanField(default=False)
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
