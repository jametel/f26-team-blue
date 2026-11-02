from django.db import transaction
from django.db.models import Max

from core.models import Queue, SongDecision, SongRequest
from core.services.venue import lock_venue


@transaction.atomic
def update_request_status(venue, request_id, new_status):
    lock_venue(venue)
    song_request = SongRequest.objects.select_for_update().get(pk=request_id, venue_id=venue)
    allowed = {
        SongRequest.PENDING: {SongRequest.APPROVED, SongRequest.REJECTED},
        SongRequest.APPROVED: {SongRequest.PLAYED, SongRequest.REMOVED},
    }
    if new_status not in allowed.get(song_request.status, set()):
        raise ValueError('Invalid request status transition.')
    if new_status == SongRequest.APPROVED:
        decision = song_request.decisions.order_by('-created_at', '-pk').first()
        if decision and decision.outcome == SongDecision.Outcome.REJECT:
            raise ValueError('Rejected songs cannot enter the queue.')
        last_position = Queue.objects.filter(venue_id=venue).aggregate(value=Max('position'))['value'] or 0
        Queue.objects.create(venue_id=venue, song_request_id=song_request, position=last_position + 1)
    elif new_status in (SongRequest.PLAYED, SongRequest.REMOVED):
        Queue.objects.filter(venue_id=venue, song_request_id=song_request).delete()
    song_request.status = new_status
    song_request.save(update_fields=['status'])
    return song_request


@transaction.atomic
def move_queue_entry(venue, entry_id, direction):
    if direction not in ('up', 'down'):
        raise ValueError('Invalid direction.')
    lock_venue(venue)
    entry = Queue.objects.get(pk=entry_id, venue_id=venue)
    peers = list(Queue.objects.filter(venue_id=venue, priority=entry.priority).order_by('position', 'pk'))
    index = next(i for i, item in enumerate(peers) if item.pk == entry.pk)
    other_index = index - 1 if direction == 'up' else index + 1
    if not 0 <= other_index < len(peers):
        return
    other = peers[other_index]
    position = entry.position
    last = Queue.objects.filter(venue_id=venue).aggregate(value=Max('position'))['value'] or 0
    entry.position = last + 1
    entry.save(update_fields=['position'])
    Queue.objects.filter(pk=other.pk).update(position=position)
    entry.position = other.position
    entry.save(update_fields=['position'])


@transaction.atomic
def set_queue_priority(venue, entry_id, priority):
    if not -10 <= priority <= 10:
        raise ValueError('Priority must be between -10 and 10.')
    lock_venue(venue)
    entry = Queue.objects.get(pk=entry_id, venue_id=venue)
    entry.priority = priority
    entry.save(update_fields=['priority'])
