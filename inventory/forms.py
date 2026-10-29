from django import forms

from core.forms import StyledFormMixin
from inventory.models import Category, Location, Product, Supplier


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'barcode', 'category', 'unit', 'cost_price', 'sale_price', 'min_qty', 'is_active']
        labels = {
            'name': 'Nomi', 'barcode': 'Shtrix-kod', 'category': 'Kategoriya', 'unit': "O'lchov birligi",
            'cost_price': 'Tannarx', 'sale_price': 'Sotuv narxi', 'min_qty': 'Minimal qoldiq', 'is_active': 'Faol',
        }
        widgets = {
            'barcode': forms.TextInput(attrs={
                'autocomplete': 'off', 'spellcheck': 'false', 'data-barcode-input': '1',
            }),
        }
        help_texts = {'barcode': 'Ixtiyoriy. Maydonni tanlab skanerlang yoki kodni yozing.'}
        error_messages = {'barcode': {'unique': 'Bu shtrix-kod boshqa tovarga biriktirilgan.'}}

    def clean_barcode(self):
        # Bo'sh kodlar NULL: bir nechta kodsiz tovarni saqlash mumkin.
        return (self.cleaned_data.get('barcode') or '').strip() or None


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        labels = {'name': 'Nomi'}


class SupplierForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'phone', 'note']
        labels = {'name': 'Nomi', 'phone': 'Telefon', 'note': 'Izoh'}


class TransferForm(StyledFormMixin, forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True), widget=forms.HiddenInput)
    from_location = forms.ChoiceField(choices=Location.choices, initial=Location.WAREHOUSE, label='Qayerdan')
    qty = forms.DecimalField(min_value=0.001, max_digits=14, decimal_places=3, label='Miqdor')

    def clean(self):
        data = super().clean()
        product, qty, loc = data.get('product'), data.get('qty'), data.get('from_location')
        if product and qty and product.qty_at(loc) < qty:
            raise forms.ValidationError("Yetarli tovar yo'q")
        return data
