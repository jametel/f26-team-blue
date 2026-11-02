from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import roles
from core.decorators import role_required
from core.models import Queue, Song, SongDecision, SongRequest, UserProfile, Venue
from core.services.musicbrainz import MusicBrainzClient, MusicBrainzError
from core.services.queue import move_queue_entry, set_queue_priority, update_request_status
from core.services.vibe_engine import evaluate_request, record_decision
from core.services.venue_qr import venue_public_url, venue_qr_png
from core.services.venue import lock_venue
from core.venue_context import current_venue


def home(request):
    return render(request, 'core/home.html', {'venues': Venue.objects.order_by('name')})


def select_venue(request, venue_slug):
    venue = current_venue(request, venue_slug)
    return redirect('venue_song_search', venue_slug=venue.slug)


@role_required([roles.STAFF, roles.OWNER])
def venue_qr(request, venue_slug):
    venue = get_object_or_404(Venue, slug=venue_slug)
    if not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden('You cannot manage this venue.')
    try:
        public_url = venue_public_url(venue)
    except ImproperlyConfigured as error:
        return render(request, 'core/venue_qr.html', {'venue': venue, 'configuration_error': str(error)})
    return render(request, 'core/venue_qr.html', {'venue': venue, 'public_url': public_url})


@role_required([roles.STAFF, roles.OWNER])
def venue_qr_image(request, venue_slug):
    venue = get_object_or_404(Venue, slug=venue_slug)
    if not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden('You cannot manage this venue.')
    try:
        image = venue_qr_png(venue)
    except ImproperlyConfigured:
        return HttpResponse('Venue QR code is not configured.', status=503, content_type='text/plain')
    response = HttpResponse(image, content_type='image/png')
    if request.GET.get('download') == '1':
        response['Content-Disposition'] = f'attachment; filename="{venue.slug}-qr.png"'
    return response


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
    query = request.GET.get("q", "").strip()
    results = []
    search_error = False
    if query:
        # Issue #2 (static song search): serve from the local database first so
        # repeated searches don't hit MusicBrainz. When the library is empty for
        # this term, fetch from MusicBrainz and persist the hits so they become
        # static on the next search.
        local = Song.objects.filter(Q(title__icontains=query) | Q(artist__icontains=query)).order_by("-id")[:10]
        if not local.exists():
            try:
                songs = MusicBrainzClient().search_songs(query)
            except MusicBrainzError:
                songs = []
                search_error = True
            found = []
            for item in songs:
                mb_id = item.get("musicbrainz_id", "")
                if not mb_id:
                    continue
                song, _ = Song.objects.update_or_create(
                    musicbrainz_id=mb_id,
                    defaults={
                        "title": item["name"],
                        "artist": item["artist"]["name"],
                    },
                )
                found.append(song)
            local = found
        results = [_song_to_result(s) for s in local]
    return render(request, "core/song_search.html", {
        "query": query,
        "results": results,
        "venue": venue,
        "search_error": search_error,
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
        messages.success(request, "Welcome to RhythmiQ! Your account has been created.")
        return redirect("dashboard")
    return render(request, "core/register.html", {"form": form})


@login_required
def dashboard(request):
    """Open the role dashboard, or help the user choose an accessible venue."""
    role = roles.get_role(request.user)
    venue = current_venue(request)
    if venue and role in (roles.OWNER, roles.STAFF):
        if role == roles.OWNER and (request.user.is_superuser or venue.owner_id == request.user.pk):
            return redirect("owner_dashboard")
        if roles.can_manage_venue(request.user, venue):
            return redirect("staff_dashboard")
        venue = None
    if venue:
        return redirect("customer_dashboard")

    venues = Venue.objects.order_by('name')
    if role in (roles.OWNER, roles.STAFF) and not request.user.is_superuser:
        venues = venues.filter(Q(owner=request.user) | Q(staff=request.user)).distinct()
    return render(request, "core/dashboard_venues.html", {"venues": venues})


@login_required
def select_dashboard_venue(request, venue_slug):
    venue = get_object_or_404(Venue, slug=venue_slug)
    role = roles.get_role(request.user)
    if role in (roles.OWNER, roles.STAFF) and not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    request.session['venue_slug'] = venue.slug
    return redirect('dashboard')


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

    with transaction.atomic():
        venue = lock_venue(venue)
        mine = _patron_requests(request, venue)
        if not venue.requests_enabled:
            messages.info(request, "Song requests are currently unavailable at this venue.")
        elif mine.filter(song_id=song, status=SongRequest.PENDING).exists():
            messages.info(request, f"You already have a pending request for \"{song.title}\".")
        elif mine.filter(status=SongRequest.PENDING).count() >= MAX_PENDING_PER_PATRON:
            messages.error(
                request,
                f"You have {MAX_PENDING_PER_PATRON} pending requests. "
                "Wait for some to be reviewed before adding more.",
            )
        else:
            decision = evaluate_request(venue, song)
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


@role_required([roles.STAFF, roles.OWNER])
@require_POST
def set_request_availability(request, venue_slug):
    venue = get_object_or_404(Venue, slug=venue_slug)
    if not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    value = request.POST.get('enabled')
    if value not in ('true', 'false'):
        return HttpResponseBadRequest('Invalid request availability.')
    with transaction.atomic():
        venue = lock_venue(venue)
        venue.requests_enabled = value == 'true'
        venue.save(update_fields=['requests_enabled'])
    messages.success(request, 'Request availability updated.')
    return redirect('venue_staff_dashboard', venue_slug=venue.slug)


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
        "queue": Queue.objects.filter(venue_id=venue)
        .select_related('song_request_id__song_id').order_by('-priority', 'position', 'pk'),
    })


@role_required([roles.STAFF, roles.OWNER])
@require_POST
def update_request(request, request_id, venue_slug=None):
    venue = current_venue(request, venue_slug)
    if not venue or not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    song_request = get_object_or_404(SongRequest, pk=request_id, venue_id=venue)
    new_status = request.POST.get("status")
    try:
        update_request_status(venue, song_request.pk, new_status)
        messages.success(request, f"\"{song_request.song_id.title}\" marked {new_status.lower()}.")
    except ValueError as error:
        messages.error(request, str(error))
    except SongRequest.DoesNotExist:
        raise Http404('Request not found.')
    return redirect("venue_staff_dashboard", venue_slug=venue.slug)


@role_required([roles.STAFF, roles.OWNER])
@require_POST
def change_queue(request, venue_slug, entry_id):
    venue = current_venue(request, venue_slug)
    if not roles.can_manage_venue(request.user, venue):
        return HttpResponseForbidden("You cannot manage this venue.")
    entry = get_object_or_404(Queue, pk=entry_id, venue_id=venue, song_request_id__venue_id=venue)
    action = request.POST.get('action')
    try:
        if action in ('up', 'down'):
            move_queue_entry(venue, entry.pk, action)
        elif action == 'priority':
            try:
                priority = int(request.POST.get('priority', ''))
            except ValueError:
                raise ValueError('Priority must be a number between -10 and 10.') from None
            set_queue_priority(venue, entry.pk, priority)
        elif action == 'remove':
            update_request_status(venue, entry.song_request_id_id, SongRequest.REMOVED)
        else:
            raise ValueError('Invalid queue action.')
    except ValueError as error:
        messages.error(request, str(error))
    except (Queue.DoesNotExist, SongRequest.DoesNotExist):
        raise Http404('Queue entry not found.')
    return redirect('venue_staff_dashboard', venue_slug=venue.slug)


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
