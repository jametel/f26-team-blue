from django.shortcuts import render

def home(request):
    return render(request, 'core/home.html')

from core.services.soundcharts import SoundchartsClient

def song_search(request):
    query = request.GET.get("q", "")
    results = []
    if query:
        client = SoundchartsClient()
        results = client.search_songs(query)
    return render(request, "core/song_search.html", {
        "query": query,
        "results": results,
    })