import uuid
from django.db import migrations, models


def generate_unique_uuids(apps, schema_editor):
    BillingRecord = apps.get_model("dashboard", "BillingRecord")
    for record in BillingRecord.objects.filter(public_id__isnull=True):
        record.public_id = uuid.uuid4()
        record.save(update_fields=["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0083_remove_billingrecord_razorpay_order_id_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="billingrecord",
            name="payment_date",
        ),
        migrations.AddField(
            model_name="billingrecord",
            name="public_id",
            field=models.UUIDField(null=True, editable=False),  # Temporarily allow NULL
        ),
        migrations.RunPython(generate_unique_uuids),  # Populate unique values
        migrations.AlterField(
            model_name="billingrecord",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True
            ),  # Enforce uniqueness after population
        ),
    ]
