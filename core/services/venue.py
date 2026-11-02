from core.models import Venue


def lock_venue(venue):
    """Serialize request and queue changes for a venue inside a transaction."""
    return Venue.objects.select_for_update().get(pk=venue.pk)
