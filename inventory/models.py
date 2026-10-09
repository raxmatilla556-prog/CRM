from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F


class Location(models.TextChoices):
    STORE = 'store', "Do'kon"
    WAREHOUSE = 'warehouse', 'Ombor'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        PIECE = 'dona', 'dona'
        KG = 'kg', 'kg'
        LITER = 'litr', 'litr'
        PACK = 'pachka', 'pachka'
        METER = 'metr', 'metr'

    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PIECE)
    cost_price = models.DecimalField('Tannarx', max_digits=14, decimal_places=2, default=0)
    sale_price = models.DecimalField('Sotuv narxi', max_digits=14, decimal_places=2, default=0)
    store_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    warehouse_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    min_qty = models.DecimalField('Minimal qoldiq', max_digits=14, decimal_places=3, default=5)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_qty(self):
        return self.store_qty + self.warehouse_qty

    @property
    def is_low(self):
        return self.total_qty <= self.min_qty

    def qty_at(self, location):
        return self.store_qty if location == Location.STORE else self.warehouse_qty

    def add_qty(self, location, delta):
        """Qoldiqni atomik o'zgartiradi (bir vaqtda bir nechta sotuvga chidamli)."""
        field = 'store_qty' if location == Location.STORE else 'warehouse_qty'
        Product.objects.filter(pk=self.pk).update(**{field: F(field) + delta})
        self.refresh_from_db(fields=['store_qty', 'warehouse_qty'])

    @classmethod
    def low_stock(cls):
        return cls.objects.filter(is_active=True, store_qty__lte=F('min_qty') - F('warehouse_qty'))


class Receipt(models.Model):
    """Yetkazib beruvchidan kirim (omborga)."""

    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        ordering = ['-created_at']


class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='receipt_items')
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True)

    @property
    def total(self):
        return self.qty * self.cost_price


class Transfer(models.Model):
    """Ombor <-> do'kon o'rtasida tovar ko'chirish."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transfers')
    from_location = models.CharField(max_length=10, choices=Location.choices)
    to_location = models.CharField(max_length=10, choices=Location.choices)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class StockCount(models.Model):
    """Inventarizatsiya: haqiqiy sanoq bilan tizimdagi qoldiqni solishtirish."""

    location = models.CharField(max_length=10, choices=Location.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def loss_value(self):
        return sum((i.difference_value for i in self.items.all()), Decimal('0'))


class StockCountItem(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    system_qty = models.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    @property
    def difference(self):
        return self.actual_qty - self.system_qty

    @property
    def difference_value(self):
        return self.difference * self.cost_price
