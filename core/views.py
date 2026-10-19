from django.shortcuts import render
from core.decorators import role_required
from core.models import Song, SongRequest #allows accesss to both models
from core.services.musicbrainz import MusicBrainzClient


def home(request):
    return render(request, 'core/home.html')


def _song_to_result(song):
    """Convert a persisted Song into the shape the template expects."""
    return {
        "name": song.title,
        "artist": {"name": song.artist},
        "musicbrainz_id": song.musicbrainz_id,
    }


def song_search(request):
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
    })
def user_in_group(user, group_name):
     return user.is_authenticated and user.groups.filter(name=group_name).exists()

@role_required(["Staff", "Owner"])
def staff_dashboard(request):
    song_requests = (
        SongRequest.objects
        .select_related("song")
        .order_by("-requested_at")
    )

    return render(request, "core/staff_dashboard.html", {
        "song_requests": song_requests,
    }) #retrieve song requests, retrieve the associated song information, sort requests newest to oldest, send request to dashboard

@role_required(["Owner"])
def owner_dashboard(request):
    return render(request, "core/owner_dashboard.html")