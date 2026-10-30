from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0016_populate_queue')]
    operations = [
        migrations.AlterField(model_name='queue', name='position', field=models.PositiveIntegerField()),
        migrations.AddConstraint(
            model_name='queue',
            constraint=models.UniqueConstraint(fields=['venue_id', 'position'], name='unique_venue_queue_position'),
        ),
        migrations.AddConstraint(
            model_name='queue',
            constraint=models.UniqueConstraint(fields=['song_request_id'], name='unique_queued_request'),
        ),
    ]
