# Generated manually for balance_bf_original field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0007_alter_invoiceitem_transport_route"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="balance_bf_original",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                null=True,
                blank=True,
                help_text="Frozen balance B/F value at invoice creation (for dashboard stats)",
            ),
        ),
    ]

