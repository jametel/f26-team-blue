import requests

class MusicBrainzClient:
    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(self):
        self.headers = {
            # MusicBrainz requires a real identifying User-Agent
            "User-Agent": "Rhythmiq/0.1 (CS411 project; https://github.com/jametel/f26-team-blue; contact: abehr003@odu.edu)",
        }

    def search_songs(self, query):
        resp = requests.get(
            f"{self.BASE_URL}/recording/",
            params={
                "query": query,
                "fmt": "json",
                "limit": 10,
            },
            headers=self.headers,
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return self._normalize(data.get("recordings", []))

    def _normalize(self, recordings):
        """Flatten MusicBrainz's nested shape into what the template expects."""
        songs = []
        for rec in recordings:
            artist_credits = rec.get("artist-credit", [])
            artist_name = artist_credits[0]["name"] if artist_credits else "Unknown Artist"
            songs.append({
                "name": rec.get("title", "Untitled"),
                "artist": {"name": artist_name},
            })
        return songs