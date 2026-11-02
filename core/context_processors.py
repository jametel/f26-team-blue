from core.roles import OWNER, STAFF, can_manage_venue, get_role
from core.models import Venue


def role(request):
    """Expose the current user's role to every template (drives the menu)."""
    slug = request.resolver_match.kwargs.get("venue_slug") if request.resolver_match else None
    slug = slug or request.session.get("venue_slug")
    venue = Venue.objects.filter(slug=slug).first() if slug else None
    user_role = get_role(request.user)
    can_manage = bool(venue and user_role in (STAFF, OWNER) and can_manage_venue(request.user, venue))
    can_own = bool(venue and user_role == OWNER and
                   (request.user.is_superuser or venue.owner_id == request.user.pk))
    return {
        "user_role": user_role,
        "current_venue": venue,
        "can_manage_current_venue": can_manage,
        "can_own_current_venue": can_own,
    }
