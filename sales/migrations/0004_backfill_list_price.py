from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    apps.get_model('sales', 'SaleItem').objects.filter(list_price=0).update(list_price=F('price'))


class Migration(migrations.Migration):
    dependencies = [('sales', '0003_saleitem_list_price_shift_debtpayment_shift_and_more')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
