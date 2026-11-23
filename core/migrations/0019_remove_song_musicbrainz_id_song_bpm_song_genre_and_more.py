# Corrected upgrade: retain old MusicBrainz identifiers before dropping the field.
from uuid import uuid4

from django.db import migrations, models


def rekey_songs(apps, connection, mapping):
    """Change song keys and all historical foreign keys in one transaction."""
    Song = apps.get_model('core', 'Song')
    database = connection.alias
    references = []
    for model in apps.get_models():
        for field in model._meta.local_fields:
            if field.is_relation and (field.many_to_one or field.one_to_one):
                if field.remote_field and field.remote_field.model == Song:
                    references.append((model, field))

    if connection.vendor == 'postgresql':
        tables = {Song._meta.db_table} | {model._meta.db_table for model, _ in references}
        with connection.cursor() as cursor:
            for table in sorted(tables):
                cursor.execute('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE' % connection.ops.quote_name(table))
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    existing = set(Song.objects.using(database).values_list('pk', flat=True))
    source = set(mapping)
    targets = list(mapping.values())
    if not source <= existing:
        raise ValueError('A mapped song does not exist in this database.')
    if any(not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 36 for value in targets):
        raise ValueError('Song identifiers must be non-empty strings of at most 36 characters.')
    if len(set(targets)) != len(targets) or set(targets) & (existing - source):
        raise ValueError('Song identifiers collide with another song.')

    def move(old, new):
        for model, field in references:
            model.objects.using(database).filter(**{field.attname: old}).update(**{field.attname: new})
        Song.objects.using(database).filter(pk=old).update(**{Song._meta.pk.attname: new})

    reserved = existing | set(targets)
    temporary = {}
    for old in mapping:
        temp = '~' + uuid4().hex
        while temp in reserved:
            temp = '~' + uuid4().hex
        reserved.add(temp)
        temporary[old] = temp
        move(old, temp)
    for old, new in mapping.items():
        move(temporary[old], new)
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def preserve_musicbrainz_ids(apps, schema_editor):
    Song = apps.get_model('core', 'Song')
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE' % schema_editor.quote_name(Song._meta.db_table))
    mapping = dict(Song.objects.using(schema_editor.connection.alias).values_list('pk', 'musicbrainz_id'))
    rekey_songs(apps, schema_editor.connection, mapping)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0018_venue_requests_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='song', name='BPM', field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='song', name='genre', field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='song', name='is_explicit', field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='song', name='vibe_characteristics', field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='song', name='id', field=models.CharField(max_length=36, primary_key=True, serialize=False),
        ),
        migrations.RunPython(preserve_musicbrainz_ids, migrations.RunPython.noop),
        migrations.RemoveField(model_name='song', name='musicbrainz_id'),
    ]
