from django.db import migrations


def copy_features(apps, schema_editor):
    Song = apps.get_model('core', 'Song')
    Features = apps.get_model('core', 'SongFeatures')
    for song in Song.objects.all().iterator():
        if song.genre is not None or song.BPM is not None or song.is_explicit is not None:
            Features.objects.get_or_create(song_id=song.pk, defaults={
                'genre': song.genre, 'bpm': song.BPM,
                'is_explicit': song.is_explicit, 'source': 'legacy-unverified',
            })


def restore_features(apps, schema_editor):
    Song = apps.get_model('core', 'Song')
    Features = apps.get_model('core', 'SongFeatures')
    for features in Features.objects.all().iterator():
        Song.objects.filter(pk=features.song_id).update(
            genre=features.genre, BPM=features.bpm, is_explicit=features.is_explicit,
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0011_song_features')]
    operations = [migrations.RunPython(copy_features, restore_features)]
