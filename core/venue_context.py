from django.shortcuts import get_object_or_404

from core.models import Venue


def current_venue(request, venue_slug=None):
    if venue_slug:
        venue = get_object_or_404(Venue, slug=venue_slug)
        request.session['venue_slug'] = venue.slug
        return venue
    slug = request.session.get('venue_slug')
    return Venue.objects.filter(slug=slug).first() if slug else None
