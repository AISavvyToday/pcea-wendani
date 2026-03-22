from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("communications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="smsnotification",
            name="message_id",
            field=models.CharField(blank=True, help_text="Central SMS service message identifier", max_length=100),
        ),
    ]
