from django.db import migrations


def populate_queue(apps, schema_editor):
    Queue = apps.get_model('core', 'Queue')
    Request = apps.get_model('core', 'SongRequest')
    Decision = apps.get_model('core', 'SongDecision')
    alias = schema_editor.connection.alias
    entries = Queue.objects.using(alias).select_related('song_request_id').order_by('added_at', 'pk')
    seen = set()
    positions = {}
    for entry in entries:
        request = entry.song_request_id
        latest = Decision.objects.using(alias).filter(request_id=request.pk).order_by('-created_at', '-pk').first()
        if (request.pk in seen or request.venue_id_id != entry.venue_id_id
                or request.status != 'APPROVED' or (latest and latest.outcome == 'REJECT')):
            raise RuntimeError('Resolve duplicate, mismatched, or rejected queue entries before migrating.')
        seen.add(request.pk)
        positions[entry.venue_id_id] = positions.get(entry.venue_id_id, 0) + 1
        entry.position = positions[entry.venue_id_id]
        entry.save(update_fields=['position'], using=alias)

    requests = Request.objects.using(alias).filter(status='APPROVED', venue_id__isnull=False).order_by('created_at', 'pk')
    for request in requests.iterator():
        if request.pk in seen:
            continue
        latest = Decision.objects.using(alias).filter(request_id=request.pk).order_by('-created_at', '-pk').first()
        if latest and latest.outcome == 'REJECT':
            raise RuntimeError('Resolve rejected decisions on approved requests before migrating.')
        venue_id = request.venue_id_id
        positions[venue_id] = positions.get(venue_id, 0) + 1
        Queue.objects.using(alias).create(
            venue_id_id=venue_id, song_request_id_id=request.pk, position=positions[venue_id],
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0015_queue_fields')]
    operations = [migrations.RunPython(populate_queue, migrations.RunPython.noop)]
