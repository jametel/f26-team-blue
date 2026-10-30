from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import roles
from core.decorators import role_required
from core.models import Song, SongDecision, SongRequest, UserProfile, Venue
from core.services.musicbrainz import MusicBrainzClient
from core.services.vibe_engine import evaluate_request, record_decision
from core.venue_context import current_venue


def home(request):
    return render(request, 'core/home.html', {'venues': Venue.objects.order_by('name')})


def select_venue(request, venue_slug):
    venue = current_venue(request, venue_slug)
    return redirect('venue_song_search', venue_slug=venue.slug)


def _song_to_result(song):
    """Convert a persisted Song into the shape the template expects."""
    return {
        "id": song.id,
        "name": song.title,
        "artist": {"name": song.artist},
        "musicbrainz_id": song.musicbrainz_id,
    }


def song_search(request, venue_slug=None):
    venue = current_venue(request, venue_slug)
    query = request.GET.get("q", "")
    results = []
    if query:
        # Issue #2 (static song search): serve from the local database first so
        # repeated searches don't hit MusicBrainz. When the library is empty for
        # this term, fetch from MusicBrainz and persist the hits so they become
        # static on the next search.
        local = Song.objects.filter(title__icontains=query).order_by("-id")[:10]
        if not local.exists():
            client = MusicBrainzClient()
            for item in client.search_songs(query):
                mb_id = item.get("musicbrainz_id", "")
                if not mb_id:
                    continue
                Song.objects.update_or_create(
                    musicbrainz_id=mb_id,
                    defaults={
                        "title": item["name"],
                        "artist": item["artist"]["name"],
                    },
                )
            local = Song.objects.filter(title__icontains=query).order_by("-id")[:10]
        results = [_song_to_result(s) for s in local]
    return render(request, "core/song_search.html", {
        "query": query,
        "results": results,
        "venue": venue,
    })


# ---------------------------------------------------------------------------
# Authentication (#8)
# ---------------------------------------------------------------------------

def register(request):
    """Customer self-registration. New accounts always get the Customer role."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        roles.set_role(user, roles.CUSTOMER)
        login(request, user)
        messages.success(request, "Welcome to Rhythmiq! Your account has been created.")
        return redirect("dashboard")
    return render(request, "core/register.html", {"form": form})


@login_required
def dashboard(request):
    """Send each logged-in user to the dashboard for their role."""
    role = roles.get_role(request.user)
    if role == roles.OWNER:
        return redirect("owner_dashboard")
    if role == roles.STAFF:
        return redirect("staff_dashboard")
    return redirect("customer_dashboard")


# ---------------------------------------------------------------------------
# Customer (#7): no login needed. Patrons are identified by their session.
# ---------------------------------------------------------------------------

MAX_PENDING_PER_PATRON = 5


def _patron_requests(request, venue):
    """Requests belonging to this visitor: their session, or their account."""
    query = Q(session_key=request.session.session_key) if request.session.session_key else Q(pk__in=[])
    if request.user.is_authenticated:
        query |= Q(requested_by=request.user)
    return SongRequest.objects.filter(query, venue_id=venue)


def customer_dashboard(request, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue:
        messages.info(request, "Choose a venue to see your requests.")
        return redirect('home')
    my_requests = (
        _patron_requests(request, venue).select_related("song_id").order_by("-created_at")
    )
    return render(request, "core/customer_dashboard.html", {"requests": my_requests})


@require_POST
def request_song(request, song_id, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue:
        messages.info(request, "Choose a venue before requesting a song.")
        return redirect('home')
    song = get_object_or_404(Song, pk=song_id)
    if not request.session.session_key:
        request.session.create()

    mine = _patron_requests(request, venue)
    if mine.filter(song_id=song, status=SongRequest.PENDING).exists():
        messages.info(request, f"You already have a pending request for \"{song.title}\".")
    elif mine.filter(status=SongRequest.PENDING).count() >= MAX_PENDING_PER_PATRON:
        messages.error(
            request,
            f"You have {MAX_PENDING_PER_PATRON} pending requests. "
            "Wait for some to be reviewed before adding more.",
        )
    else:
        decision = evaluate_request(venue, song)
        with transaction.atomic():
            song_request = None
            if decision.outcome != SongDecision.Outcome.REJECT:
                song_request = SongRequest.objects.create(
                    song_id=song,
                    venue_id=venue,
                    session_key=request.session.session_key,
                    requested_by=request.user if request.user.is_authenticated else None,
                    user_id=UserProfile.objects.get_or_create(user=request.user)[0]
                    if request.user.is_authenticated else None,
                )
            record_decision(venue, song, decision, song_request)
        if decision.outcome == SongDecision.Outcome.REJECT:
            messages.error(request, f"{song.title} does not meet this venue's music settings.")
        elif decision.outcome == SongDecision.Outcome.REVIEW:
            messages.info(request, f"{song.title} needs staff review.")
        else:
            messages.success(request, f"Requested \"{song.title}\".")
    return redirect("venue_customer_dashboard", venue_slug=venue.slug)


# ---------------------------------------------------------------------------
# Staff (#7): review the request queue
# ---------------------------------------------------------------------------

@role_required([roles.STAFF, roles.OWNER])
def staff_dashboard(request, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue:
        messages.info(request, "Choose a venue to manage requests.")
        return redirect('home')
    if not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    song_requests = (
        SongRequest.objects.filter(venue_id=venue)
        .select_related("song_id", "requested_by")
        .prefetch_related(Prefetch('decisions', queryset=SongDecision.objects.order_by('-created_at'),
                                   to_attr='vibe_decisions'))
        .order_by("-created_at")
    )
    return render(request, "core/staff_dashboard.html", {
        "song_requests": song_requests,
    })


@role_required([roles.STAFF, roles.OWNER])
@require_POST
def update_request(request, request_id, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue or not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    song_request = get_object_or_404(SongRequest, pk=request_id, venue_id=venue)
    new_status = request.POST.get("status")
    transitions = {
        SongRequest.PENDING: {SongRequest.APPROVED, SongRequest.REJECTED},
        SongRequest.APPROVED: {SongRequest.PLAYED},
    }
    if new_status not in transitions.get(song_request.status, set()):
        messages.error(request, "Invalid status.")
    else:
        song_request.status = new_status
        song_request.save(update_fields=["status"])
        messages.success(request, f"\"{song_request.song_id.title}\" marked {new_status.lower()}.")
    return redirect("venue_staff_dashboard", venue_slug=venue.slug)


# ---------------------------------------------------------------------------
# Owner (#7): stats and role management
# ---------------------------------------------------------------------------

@role_required([roles.OWNER])
def owner_dashboard(request, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue:
        messages.info(request, "Choose a venue to manage it.")
        return redirect('home')
    if not (request.user.is_superuser or venue.owner_id == request.user.pk):
        return HttpResponseForbidden("You do not own this venue.")
    User = get_user_model()
    status_counts = dict(
        SongRequest.objects.filter(venue_id=venue).values_list("status").annotate(n=Count("id"))
    )
    users = [
        {"user": u, "role": roles.get_role(u)}
        for u in User.objects.filter(Q(pk=venue.owner_id) | Q(staff_venues=venue)).distinct().order_by("username")
    ]
    return render(request, "core/owner_dashboard.html", {
        "status_counts": status_counts,
        "total_requests": sum(status_counts.values()),
        "users": users,
        "assignable_roles": [roles.CUSTOMER, roles.STAFF],
    })


@role_required([roles.OWNER])
@require_POST
def set_user_role(request, user_id, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue or not (request.user.is_superuser or venue.owner_id == request.user.pk):
        return HttpResponseForbidden("You do not own this venue.")
    target = get_object_or_404(get_user_model(), pk=user_id)
    new_role = request.POST.get("role")
    if not venue.staff.filter(pk=target.pk).exists():
        return HttpResponseForbidden("This user is not staff at this venue.")
    if target.staff_venues.exclude(pk=venue.pk).exists() or target.owned_venues.exists():
        return HttpResponseForbidden("This user also belongs to another venue.")
    if new_role not in (roles.CUSTOMER, roles.STAFF):
        messages.error(request, "Invalid role.")
    elif target == request.user:
        messages.error(request, "You can't change your own role.")
    elif target.is_superuser:
        messages.error(request, "Superuser roles are managed in the admin site.")
    else:
        roles.set_role(target, new_role)
        messages.success(request, f"{target.username} is now {new_role}.")
    return redirect("venue_owner_dashboard", venue_slug=venue.slug)
