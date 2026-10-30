import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_safe_upgrade'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='song', name='BPM', field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='song', name='genre', field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='song', name='is_explicit', field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='songrequest', name='user_id',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to='core.userprofile'),
        ),
        migrations.AlterField(
            model_name='songrequest', name='venue_id',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to='core.venue'),
        ),
        migrations.AddField(
            model_name='songrequest', name='requested_by',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='song_requests', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='songrequest', name='session_key',
            field=models.CharField(max_length=40, blank=True, db_index=True),
        ),
    ]
