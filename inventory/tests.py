import json

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import User
from inventory.forms import ProductForm
from inventory.models import Product
from sales.models import Sale, Shift


class BarcodeFormTests(TestCase):
    def form(self, barcode='', instance=None, **extra):
        return ProductForm({
            'name': 'Sut', 'barcode': barcode, 'unit': 'dona', 'cost_price': '9000',
            'sale_price': '11000', 'min_qty': '5', 'is_active': 'on', **extra,
        }, instance=instance)

    def test_leading_zeros_survive_and_outer_whitespace_is_trimmed(self):
        form = self.form('  0012345678905  ')
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        product.refresh_from_db()
        self.assertEqual(product.barcode, '0012345678905')

    def test_multiple_products_can_have_no_barcode(self):
        for value in ('', '   ', None):
            form = self.form(value)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.save().barcode)
        self.assertEqual(Product.objects.filter(barcode__isnull=True).count(), 3)

    def test_duplicate_is_rejected_even_if_original_product_is_inactive(self):
        Product.objects.create(name='Eski sut', barcode='0012345678905', is_active=False)
        form = self.form('0012345678905')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['barcode'], ['Bu shtrix-kod boshqa tovarga biriktirilgan.'])

    def test_database_also_rejects_duplicate_barcodes(self):
        Product.objects.create(name='Birinchi', barcode='ABC-001')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(name='Ikkinchi', barcode='ABC-001')

    def test_existing_product_can_keep_or_clear_its_code(self):
        product = self.form('ABC-001').save()
        form = self.form('ABC-001', instance=product, name='Yangi nom')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().barcode, 'ABC-001')
        form = self.form('', instance=product)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().barcode)

    def test_code_length_is_validated(self):
        form = self.form('0' * 65)
        self.assertFalse(form.is_valid())
        self.assertIn('barcode', form.errors)


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_OWNER_CHAT_ID='')
class BarcodeSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='owner', role=User.Role.OWNER)
        cls.seller = User.objects.create_user(username='seller', role=User.Role.SELLER)
        cls.warehouse = User.objects.create_user(username='warehouse', role=User.Role.WAREHOUSE)
        cls.product = Product.objects.create(
            name='Sut', barcode='0012345678905', cost_price=9000, sale_price=11000,
            store_qty=5, warehouse_qty=20,
        )
        cls.alpha_product = Product.objects.create(name='Choy', barcode='TEA-A01')
        cls.inactive = Product.objects.create(name='Eski tovar', barcode='9999999999999', is_active=False)

    def setUp(self):
        self.client.force_login(self.seller)

    def search(self, query):
        response = self.client.get(reverse('inventory:product_api'), {'q': query})
        self.assertEqual(response.status_code, 200)
        return response.json()['results']

    def test_exact_barcode_wins_over_name_matches_and_result_limit(self):
        Product.objects.bulk_create([
            Product(name=f'A {i} 0012345678905', sale_price=1) for i in range(60)
        ])
        results = self.search(' 0012345678905 ')
        self.assertEqual([p['id'] for p in results], [self.product.pk])
        self.assertEqual(results[0]['barcode'], '0012345678905')
        self.assertEqual(results[0]['sale_price'], '11000.00')
        self.assertIsNone(results[0]['cost_price'])

    def test_alphanumeric_code_is_supported(self):
        self.assertEqual([p['id'] for p in self.search('TEA-A01')], [self.alpha_product.pk])

    def test_partial_unknown_and_inactive_codes_do_not_match(self):
        for query in ('001234', '12345678905', 'unknown-code', self.inactive.barcode):
            with self.subTest(query=query):
                self.assertEqual(self.search(query), [])

    def test_name_search_still_works(self):
        other = Product.objects.create(name='Qaynatilgan sut')
        self.assertEqual([p['id'] for p in self.search('sut')], [self.product.pk, other.pk])

    def test_stock_page_searches_by_barcode(self):
        response = self.client.get(reverse('inventory:stock'), {'q': self.product.barcode})
        self.assertEqual([p.pk for p in response.context['page']], [self.product.pk])
        self.assertContains(response, self.product.barcode)

    def test_existing_permissions_apply_to_barcode_search_and_edit(self):
        for user in (self.owner, self.warehouse):
            self.client.force_login(user)
            self.assertEqual(self.search(self.product.barcode)[0]['cost_price'], '9000.00')
            response = self.client.get(reverse('inventory:product_edit', args=[self.product.pk]))
            self.assertContains(response, 'name="barcode"')
        self.client.force_login(self.seller)
        response = self.client.post(reverse('inventory:product_edit', args=[self.product.pk]), {
            'barcode': 'changed',
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.barcode, '0012345678905')
        self.client.logout()
        response = self.client.get(reverse('inventory:product_api'), {'q': self.product.barcode})
        self.assertEqual(response.status_code, 302)

    def test_warehouse_can_save_barcode_on_existing_product(self):
        self.client.force_login(self.warehouse)
        response = self.client.post(reverse('inventory:product_edit', args=[self.product.pk]), {
            'name': 'Sut', 'barcode': '0000000000001', 'unit': 'dona', 'cost_price': '9000',
            'sale_price': '11000', 'min_qty': '5', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.barcode, '0000000000001')
        self.assertEqual(self.product.store_qty, 5)

    def test_barcode_search_connects_to_existing_checkout(self):
        Shift.objects.create(seller=self.seller)
        product_id = self.search(self.product.barcode)[0]['id']
        response = self.client.post(reverse('sales:checkout'), json.dumps({
            'items': [{'id': product_id, 'qty': 2}], 'cash': 22000,
        }), content_type='application/json')
        self.assertTrue(response.json()['ok'], response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_qty, 3)
        self.assertEqual(self.product.warehouse_qty, 20)
        self.assertEqual(Sale.objects.get().items.get().product_id, product_id)

    def test_barcode_labels_render_in_russian(self):
        self.owner.language = 'ru'
        self.owner.save(update_fields=['language'])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('inventory:product_create')), 'Штрихкод')
        self.assertContains(self.client.get(reverse('sales:pos')), 'Название товара или штрихкод')
