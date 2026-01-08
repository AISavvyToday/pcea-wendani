# Generated migration to alter report_type field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reportrequest",
            name="report_type",
            field=models.CharField(max_length=50),
        ),
    ]

