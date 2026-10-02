from django.shortcuts import render
from core.decorators import role_required


def home(request):
    return render(request, 'core/home.html')

from core.services.musicbrainz import MusicBrainzClient

def song_search(request):
    query = request.GET.get("q", "")
    results = []
    if query:
        client = MusicBrainzClient()
        results = client.search_songs(query)
    return render(request, "core/song_search.html", {
        "query": query,
        "results": results,
    })
def user_in_group(user, group_name):
     return user.is_authenticated and user.groups.filter(name=group_name).exists()

@role_required(["Staff", "Owner"])
def staff_dashboard(request):
    return render(request, "core/staff_dashboard.html")

@role_required(["Owner"])
def owner_dashboard(request):
    return render(request, "core/owner_dashboard.html")