from core.roles import get_role
from core.models import Venue


def role(request):
    """Expose the current user's role to every template (drives the menu)."""
    slug = request.resolver_match.kwargs.get("venue_slug") if request.resolver_match else None
    slug = slug or request.session.get("venue_slug")
    venue = Venue.objects.filter(slug=slug).first() if slug else None
    return {"user_role": get_role(request.user), "current_venue": venue}
