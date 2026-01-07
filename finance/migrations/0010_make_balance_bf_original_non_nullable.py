# Generated manually to make balance_bf_original non-nullable

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0009_populate_balance_bf_original"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="balance_bf_original",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                help_text="Frozen balance B/F value at invoice creation (for dashboard stats)",
            ),
        ),
    ]

