from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0002_remove_product_barcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='barcode',
            field=models.CharField(
                'Shtrix-kod', max_length=64, unique=True, blank=True, null=True,
            ),
        ),
    ]
