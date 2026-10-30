from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0009_request_venue_scope')]
    operations = [
        migrations.AddConstraint(
            model_name='songrequest',
            constraint=models.CheckConstraint(
                condition=models.Q(venue_id__isnull=False) | models.Q(legacy_unassigned=True),
                name='request_has_venue_or_is_legacy',
            ),
        ),
    ]
