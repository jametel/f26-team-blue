import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0013_remove_song_metadata')]
    operations = [
        migrations.CreateModel(
            name='SongDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('outcome', models.CharField(max_length=10, choices=[('ACCEPT', 'Accepted'), ('REJECT', 'Rejected'), ('REVIEW', 'Staff review')])),
                ('reasons', models.JSONField(default=list)),
                ('inputs', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('venue', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='decisions', to='core.venue')),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='decisions', to='core.song')),
                ('request', models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name='decisions', to='core.songrequest')),
            ],
        ),
    ]
