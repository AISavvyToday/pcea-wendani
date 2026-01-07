# Generated manually to populate balance_bf_original from balance_bf

from django.db import migrations
from django.db.models import F


def populate_balance_bf_original(apps, schema_editor):
    """Populate balance_bf_original from balance_bf for all existing invoices."""
    Invoice = apps.get_model("finance", "Invoice")
    Invoice.objects.all().update(balance_bf_original=F("balance_bf"))


def reverse_populate_balance_bf_original(apps, schema_editor):
    """Reverse migration - set balance_bf_original to 0."""
    Invoice = apps.get_model("finance", "Invoice")
    Invoice.objects.all().update(balance_bf_original=0)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0008_invoice_balance_bf_original"),
    ]

    operations = [
        migrations.RunPython(
            populate_balance_bf_original,
            reverse_populate_balance_bf_original,
        ),
    ]

