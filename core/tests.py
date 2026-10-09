import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ActionLog, JobRun, User
from inventory.models import Product, Receipt, ReceiptItem
from inventory.views import expiring_items
from sales.models import Customer, DebtPayment, Shift
from sales.services import create_sale


def make_user(username, role, must_change=False):
    user = User(username=username, role=role, must_change_password=must_change)
    user.set_password('eski-parol-1')
    user.save()
    return user


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_OWNER_CHAT_ID='')
class BaseTest(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user('ega', User.Role.OWNER)
        self.seller = make_user('sotuvchi', User.Role.SELLER)
        self.product = Product.objects.create(name='Sut', cost_price=9000, sale_price=11000,
                                              store_qty=20, warehouse_qty=0)

    def checkout(self, items, cash, **extra):
        return self.client.post(reverse('sales:checkout'), json.dumps({'items': items, 'cash': cash, **extra}),
                                content_type='application/json')


class SecurityTests(BaseTest):
    def test_login_lockout_after_five_failures(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'sotuvchi', 'password': 'xato'})
        r = self.client.post(reverse('login'), {'username': 'sotuvchi', 'password': 'eski-parol-1'})
        self.assertEqual(r.status_code, 200)  # to'g'ri parol bilan ham kirmaydi
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_must_change_password_redirects_everywhere(self):
        user = make_user('yangi', User.Role.SELLER, must_change=True)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('sales:pos')), reverse('password_change'))
        r = self.client.post(reverse('password_change'), {
            'old_password': 'eski-parol-1', 'new_password1': 'Kuchli-Parol-2026', 'new_password2': 'Kuchli-Parol-2026',
        })
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertEqual(self.client.get(reverse('sales:shift')).status_code, 200)

    def test_owner_sets_staff_password_forces_change(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('user_edit', args=[self.seller.pk]), {
            'username': 'sotuvchi', 'role': 'seller', 'language': 'uz', 'is_active': 'on', 'password': 'vaqtincha1',
        })
        self.seller.refresh_from_db()
        self.assertTrue(self.seller.must_change_password)


class ShiftTests(BaseTest):
    def test_pos_requires_open_shift_for_seller(self):
        self.client.force_login(self.seller)
        self.assertRedirects(self.client.get(reverse('sales:pos')), reverse('sales:shift'))
        self.assertFalse(self.checkout([{'id': self.product.pk, 'qty': 1}], 11000).json()['ok'])

    def test_shift_expected_cash_and_difference(self):
        self.client.force_login(self.seller)
        self.client.post(reverse('sales:shift'), {'action': 'open', 'opening_cash': '50000'})
        shift = Shift.objects.get()
        c = Customer.objects.create(name='Ali')
        self.assertTrue(self.checkout([{'id': self.product.pk, 'qty': 2}], 22000).json()['ok'])
        self.assertTrue(self.checkout([{'id': self.product.pk, 'qty': 1}], 5000, customer_id=c.pk).json()['ok'])
        self.client.post(reverse('sales:customer_detail', args=[c.pk]), {'action': 'pay', 'amount': '3000'})
        sale = shift.sales.first()
        self.client.post(reverse('sales:sale_return', args=[sale.pk]), {f'qty_{sale.items.get().pk}': '1'})
        totals = shift.totals()
        # 50000 + 22000 + 5000 + 3000 - vozvrat (naqd)
        refund = shift.returns.get().cash_refund
        self.assertEqual(totals['expected'], 80000 - refund)

        self.client.post(reverse('sales:shift'), {'action': 'close', 'actual_cash': str(80000 - refund - 1000)})
        shift.refresh_from_db()
        self.assertFalse(shift.is_open)
        self.assertEqual(shift.difference, -1000)


class PriceOverrideTests(BaseTest):
    def setUp(self):
        super().setUp()
        Shift.objects.create(seller=self.seller)
        self.client.force_login(self.seller)

    def test_seller_can_change_price_above_cost_and_it_is_logged(self):
        r = self.checkout([{'id': self.product.pk, 'qty': 2, 'price': 10000}], 20000)
        self.assertTrue(r.json()['ok'])
        item = self.product.sale_items.get()
        self.assertEqual((item.price, item.list_price), (10000, 11000))
        self.assertTrue(ActionLog.objects.filter(action__contains='narxi o‘zgartirildi').exists())

    def test_seller_cannot_sell_below_cost(self):
        r = self.checkout([{'id': self.product.pk, 'qty': 1, 'price': 8000}], 8000)
        self.assertFalse(r.json()['ok'])

    def test_error_message_in_russian(self):
        self.seller.language = 'ru'
        self.seller.save()
        r = self.checkout([{'id': self.product.pk, 'qty': 999}], 0)
        self.assertIn('в магазине только', r.json()['error'])


class PaymentDeleteTests(BaseTest):
    def test_seller_deletes_own_payment_only_while_shift_open(self):
        c = Customer.objects.create(name='Ali')
        create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('1')}], cash=Decimal('0'), customer=c)
        shift = Shift.objects.create(seller=self.seller)
        p1 = DebtPayment.objects.create(customer=c, amount=5000, received_by=self.seller, shift=shift)
        self.client.force_login(self.seller)
        self.client.post(reverse('sales:payment_delete', args=[p1.pk]))
        self.assertFalse(DebtPayment.objects.filter(pk=p1.pk).exists())

        p2 = DebtPayment.objects.create(customer=c, amount=5000, received_by=self.seller, shift=shift)
        shift.closed_at = timezone.now()
        shift.save()
        self.client.post(reverse('sales:payment_delete', args=[p2.pk]))
        self.assertTrue(DebtPayment.objects.filter(pk=p2.pk).exists())
        self.client.force_login(self.owner)
        self.client.post(reverse('sales:payment_delete', args=[p2.pk]))
        self.assertFalse(DebtPayment.objects.filter(pk=p2.pk).exists())


class InventoryTests(BaseTest):
    def test_expiry_uses_fifo_batches(self):
        today = timezone.localdate()
        p = Product.objects.create(name='Qatiq', warehouse_qty=0)
        old = Receipt.objects.create()
        ReceiptItem.objects.create(receipt=old, product=p, qty=10, cost_price=1, expiry_date=today + timedelta(days=2))
        new = Receipt.objects.create()
        ReceiptItem.objects.create(receipt=new, product=p, qty=10, cost_price=1, expiry_date=today + timedelta(days=5))
        Receipt.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        # 20 dan 12 tasi sotilgan: eski partiyadan 0, yangidan 8 ta qolgan
        Product.objects.filter(pk=p.pk).update(store_qty=8)
        items = expiring_items()
        self.assertEqual([(i.receipt_id, i.remaining) for i in items], [(new.pk, 8)])

    def test_product_delete_only_without_history(self):
        self.client.force_login(self.owner)
        fresh = Product.objects.create(name='Yangi')
        self.client.post(reverse('inventory:product_delete', args=[fresh.pk]))
        self.assertFalse(Product.objects.filter(pk=fresh.pk).exists())
        create_sale(self.seller, [{'id': self.product.pk, 'qty': Decimal('1')}], cash=Decimal('11000'))
        self.client.post(reverse('inventory:product_delete', args=[self.product.pk]))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_price_change_logged_with_values(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('inventory:product_edit', args=[self.product.pk]), {
            'name': 'Sut', 'unit': 'dona', 'cost_price': '9000', 'sale_price': '12500',
            'min_qty': '5', 'is_active': 'on',
        })
        self.assertTrue(ActionLog.objects.filter(action__contains='11 000 → 12 500').exists())


class BackupAndJobsTests(BaseTest):
    def test_backup_contains_data(self):
        from core.backup import make_backup

        path = make_backup()
        try:
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read('data.json'))
            self.assertTrue(any(o['model'] == 'inventory.product' for o in data))
        finally:
            path.unlink()

    def test_jobs_run_once_per_day_after_time(self):
        from core import jobs

        calls = []
        fake = {name: (lambda n=name: calls.append(n) or (True, 'ok'), setting)
                for name, (_, setting) in jobs.JOBS.items()}
        with mock.patch.dict(jobs.JOBS, fake), \
                override_settings(DAILY_REPORT_TIME='21:00', DEBT_REMINDER_TIME='10:00', BACKUP_TIME='21:30'):
            morning = timezone.localtime().replace(hour=9, minute=0)
            self.assertEqual(jobs.run_due_jobs(morning), [])
            noon = morning.replace(hour=12)
            self.assertEqual([d[0] for d in jobs.run_due_jobs(noon)], ['debt_reminders'])
            self.assertEqual(jobs.run_due_jobs(noon), [])  # ikkinchi marta bajarilmaydi
            night = morning.replace(hour=22)
            self.assertEqual(sorted(d[0] for d in jobs.run_due_jobs(night)), ['backup', 'daily_report'])
        self.assertEqual(sorted(calls), ['backup', 'daily_report', 'debt_reminders'])
        self.assertEqual(JobRun.objects.count(), 3)

    def test_backup_page(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('backup')).status_code, 200)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse('backup')).status_code, 302)


class PagesRenderTests(BaseTest):
    def test_new_pages_render_in_both_languages(self):
        shift = Shift.objects.create(seller=self.owner)
        urls = [reverse('sales:shift'), reverse('sales:shift_list'), reverse('sales:shift_detail', args=[shift.pk]),
                reverse('password_change'), reverse('backup'), reverse('inventory:categories') + '?edit=0',
                reverse('inventory:alerts'), reverse('sales:pos')]
        self.client.force_login(self.owner)
        for lang in ('uz', 'ru'):
            self.owner.language = lang
            self.owner.save()
            for url in urls:
                with self.subTest(url=url, lang=lang):
                    self.assertIn(self.client.get(url).status_code, (200, 404))


@override_settings(SHOP_NAME='Baraka Market', SHOP_ADDRESS='Navoiy ko‘chasi 5', SHOP_PHONE='+998 90 123 45 67',
                   GOOGLE_SITE_VERIFICATION='abc123')
class SeoTests(BaseTest):
    def test_public_landing_is_indexable(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('X-Robots-Tag', r)
        html = r.content.decode()
        self.assertIn('Baraka Market', html)
        self.assertIn('"@type": "Store"', html)
        self.assertIn('google-site-verification" content="abc123"', html)

    def test_internal_pages_are_noindex(self):
        self.assertEqual(self.client.get(reverse('login'))['X-Robots-Tag'], 'noindex, nofollow')
        self.client.force_login(self.owner)
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)  # xodim o'z bo'limiga o'tadi
        self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')

    def test_robots_and_sitemap(self):
        robots = self.client.get('/robots.txt').content.decode()
        self.assertIn('Allow: /$', robots)
        self.assertIn('Disallow: /', robots)
        self.assertIn('/sitemap.xml', robots)
        self.assertIn('<loc>http://testserver/</loc>', self.client.get('/sitemap.xml').content.decode())
