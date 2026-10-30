from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('core', '0012_move_song_features')]
    operations = [
        migrations.RemoveField(model_name='song', name='genre'),
        migrations.RemoveField(model_name='song', name='BPM'),
        migrations.RemoveField(model_name='song', name='is_explicit'),
    ]
