import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import User
from inventory.models import Product, Receipt
from sales.models import Customer, DebtPayment, Sale
from sales.services import SaleError, create_sale, customers_with_balance


def make_user(username, role):
    user = User(username=username, role=role)
    user.set_password('123456')
    user.save()
    return user


# Testlarda haqiqiy Telegramga xabar ketmasligi uchun
@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_OWNER_CHAT_ID='')
class BaseTest(TestCase):
    pass


class SaleServiceTests(BaseTest):
    def setUp(self):
        self.seller = make_user('s', User.Role.SELLER)
        self.product = Product.objects.create(name='Non', cost_price=3000, sale_price=4000, store_qty=10, warehouse_qty=5)

    def test_cash_sale_reduces_store_stock_and_records_profit(self):
        sale = create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('3')}], cash=Decimal('12000'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_qty, 7)
        self.assertEqual(self.product.warehouse_qty, 5)
        self.assertEqual(sale.total, 12000)
        self.assertEqual(sale.debt_amount, 0)
        self.assertEqual(sale.profit, 3000)

    def test_cannot_sell_more_than_store_stock(self):
        with self.assertRaises(SaleError):
            create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('11')}], cash=Decimal('0'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_qty, 10)

    def test_debt_requires_customer(self):
        with self.assertRaises(SaleError):
            create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('1')}], cash=Decimal('1000'))

    def test_partial_payment_goes_to_debt_and_fifo_payments(self):
        c = Customer.objects.create(name='Ali', phone='901234567')
        today = timezone.localdate()
        s1 = create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('2')}], cash=Decimal('3000'),
                         customer=c, due_date=today - timedelta(days=1))
        s2 = create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('1')}], cash=Decimal('0'),
                         customer=c, due_date=today + timedelta(days=10))
        self.assertEqual(s1.debt_amount, 5000)
        self.assertEqual(c.balance, 9000)
        self.assertTrue(c.is_overdue)

        DebtPayment.objects.create(customer=c, amount=6000)
        unpaid = c.unpaid_sales()
        self.assertEqual([s.pk for s in unpaid], [s2.pk])
        self.assertEqual(unpaid[0].remaining, 3000)
        self.assertFalse(c.is_overdue)
        self.assertEqual(customers_with_balance().get(pk=c.pk).balance_value, 3000)


class ViewTests(BaseTest):
    def setUp(self):
        self.owner = make_user('ega', User.Role.OWNER)
        self.seller = make_user('sotuvchi', User.Role.SELLER)
        self.wh = make_user('omborchi', User.Role.WAREHOUSE)
        self.product = Product.objects.create(name='Sut', cost_price=9000, sale_price=11000,
                                              store_qty=5, warehouse_qty=20)

    def test_checkout_with_new_customer_debt(self):
        self.client.force_login(self.seller)
        self.client.post(reverse('sales:shift'), {'action': 'open', 'opening_cash': '0'})
        r = self.client.post(reverse('sales:checkout'), json.dumps({
            'items': [{'id': self.product.pk, 'qty': 2}], 'cash': 10000,
            'new_customer': {'name': 'Vali', 'phone': '+998 90 111 22 33'},
            'due_date': (timezone.localdate() + timedelta(days=7)).isoformat(),
        }), content_type='application/json')
        self.assertTrue(r.json()['ok'], r.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.debt_amount, 12000)
        self.assertEqual(sale.customer.name, 'Vali')
        self.assertEqual(self.client.get(reverse('sales:receipt', args=[sale.pk])).status_code, 200)

    def test_receipt_updates_average_cost(self):
        self.client.force_login(self.wh)
        r = self.client.post(reverse('inventory:receipt_create'), {
            'product': [self.product.pk], 'qty': ['25'], 'cost': ['10000'], 'sale_price': ['12000'], 'expiry': [''],
        })
        self.assertEqual(r.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.warehouse_qty, 45)
        # (25*9000 + 25*10000) / 50
        self.assertEqual(self.product.cost_price, Decimal('9500.00'))
        self.assertEqual(self.product.sale_price, 12000)
        self.assertEqual(Receipt.objects.get().total_cost, 250000)

    def test_transfer_moves_stock(self):
        self.client.force_login(self.wh)
        self.client.post(reverse('inventory:transfer'), {'product': self.product.pk, 'from_location': 'warehouse', 'qty': '8'})
        self.product.refresh_from_db()
        self.assertEqual((self.product.warehouse_qty, self.product.store_qty), (12, 13))

    def test_stock_count_adjusts(self):
        self.client.force_login(self.wh)
        self.client.post(reverse('inventory:count_create'), {'location': 'store', f'actual_{self.product.pk}': '3'})
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_qty, 3)

    def test_role_permissions(self):
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse('reports:dashboard')).status_code, 302)
        self.assertEqual(self.client.get(reverse('inventory:receipt_create')).status_code, 302)
        self.client.force_login(self.wh)
        self.assertEqual(self.client.get(reverse('sales:pos')).status_code, 302)

    def test_all_pages_render(self):
        c = Customer.objects.create(name='Ali')
        create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('1')}], cash=Decimal('0'), customer=c)
        self.client.force_login(self.owner)
        urls = [
            reverse('reports:dashboard'), reverse('reports:dashboard') + '?period=month',
            reverse('user_list'), reverse('user_create'), reverse('action_log'),
            reverse('sales:pos'), reverse('sales:sale_list'), reverse('sales:debt_book'),
            reverse('sales:customer_detail', args=[c.pk]), reverse('sales:customer_create'),
            reverse('inventory:stock'), reverse('inventory:product_create'), reverse('inventory:alerts'),
            reverse('inventory:receipt_list'), reverse('inventory:receipt_create'), reverse('inventory:transfer'),
            reverse('inventory:count_list'), reverse('inventory:count_create'), reverse('inventory:categories'),
            reverse('inventory:suppliers'), reverse('inventory:product_api') + '?q=Su',
            reverse('sales:customer_api') + '?q=Al',
        ]
        for lang in ('uz', 'ru'):
            self.owner.language = lang
            self.owner.save()
            for url in urls:
                with self.subTest(url=url, lang=lang):
                    self.assertEqual(self.client.get(url).status_code, 200)


class ReturnTests(BaseTest):
    def setUp(self):
        self.owner = make_user('ega', User.Role.OWNER)
        self.seller = make_user('s', User.Role.SELLER)
        self.other = make_user('s2', User.Role.SELLER)
        self.product = Product.objects.create(name='Guruch', cost_price=16000, sale_price=19000, store_qty=10)
        self.customer = Customer.objects.create(name='Akmal')

    def sell(self, qty, cash, **kw):
        return create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal(qty)}], cash=Decimal(cash), **kw)

    def test_cash_sale_return_restores_stock_and_reports(self):
        from reports.services import summary, top_products
        from sales.services import create_return

        sale = self.sell('3', '57000')
        item = sale.items.get()
        ret = create_return(self.seller, sale, {item.pk: Decimal('1')}, 'buzilgan')
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_qty, 8)
        self.assertEqual((ret.total, ret.cash_refund, ret.debt_reduction), (19000, 19000, 0))

        today = timezone.localdate()
        s = summary(today, today)
        self.assertEqual(s['revenue'], 38000)
        self.assertEqual(s['profit'], 6000)
        self.assertEqual(s['cash_in'], 38000)
        self.assertEqual(top_products(today, today)[0]['sold_qty'], 2)

    def test_cannot_return_more_than_sold(self):
        from sales.services import create_return

        sale = self.sell('2', '38000')
        item = sale.items.get()
        create_return(self.seller, sale, {item.pk: Decimal('2')})
        with self.assertRaises(SaleError):
            create_return(self.seller, sale, {item.pk: Decimal('1')})

    def test_return_reduces_customer_debt_first(self):
        from sales.services import create_return

        sale = self.sell('2', '10000', customer=self.customer)  # 38000, 28000 qarz
        ret = create_return(self.seller, sale, {sale.items.get().pk: Decimal('2')})
        self.assertEqual((ret.debt_reduction, ret.cash_refund), (28000, 10000))
        self.assertEqual(self.customer.balance, 0)
        self.assertEqual(customers_with_balance().get(pk=self.customer.pk).balance_value, 0)

    def test_discount_is_prorated(self):
        from sales.services import create_return

        sale = create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('2')}],
                           cash=Decimal('34000'), discount=Decimal('4000'))
        ret = create_return(self.seller, sale, {sale.items.get().pk: Decimal('1')})
        self.assertEqual(ret.total, 17000)

    def test_return_permissions(self):
        sale = self.sell('1', '19000')
        url = reverse('sales:sale_return', args=[sale.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 302)
        Sale.objects.filter(pk=sale.pk).update(created_at=timezone.now() - timedelta(days=2))
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {f'qty_{sale.items.get().pk}': '1', 'reason': 'test'})
        self.assertRedirects(r, reverse('sales:receipt', args=[sale.pk]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('sales:receipt', args=[sale.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('sales:sale_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports:dashboard')).status_code, 200)
