import django.db.models.deletion
from django.db import migrations, models


def mark_legacy_requests(apps, schema_editor):
    Request = apps.get_model('core', 'SongRequest')
    Request.objects.filter(venue_id__isnull=True).update(legacy_unassigned=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0008_venue_policies')]
    operations = [
        migrations.AddField(
            model_name='songrequest', name='legacy_unassigned',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='songrequest', name='venue_id',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, to='core.venue'),
        ),
        migrations.RunPython(mark_legacy_requests, migrations.RunPython.noop),
    ]
