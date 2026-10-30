import logging

import requests


logger = logging.getLogger(__name__)


class MusicBrainzError(Exception):
    pass


class MusicBrainzClient:
    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(self):
        self.headers = {
            # MusicBrainz requires a real identifying User-Agent
            "User-Agent": "Rhythmiq/0.1 (CS411 project; https://github.com/jametel/f26-team-blue; contact: abehr003@odu.edu)",
        }

    def search_songs(self, query):
        try:
            resp = requests.get(
                f"{self.BASE_URL}/recording/",
                params={"query": query, "fmt": "json", "limit": 10},
                headers=self.headers,
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or not isinstance(data.get("recordings", []), list):
                raise ValueError("Invalid MusicBrainz response")
            return self._normalize(data.get("recordings", []))
        except (requests.RequestException, ValueError) as error:
            logger.warning("MusicBrainz search failed: %s", type(error).__name__)
            raise MusicBrainzError("Music search is temporarily unavailable") from error

    def _normalize(self, recordings):
        """Flatten MusicBrainz's nested shape into what the template expects."""
        songs = []
        for rec in recordings:
            if not isinstance(rec, dict):
                continue
            title, recording_id = rec.get("title"), rec.get("id")
            if not isinstance(title, str) or not title.strip() or not isinstance(recording_id, str) or not recording_id.strip():
                continue
            artist_credits = rec.get("artist-credit")
            first_credit = artist_credits[0] if isinstance(artist_credits, list) and artist_credits else None
            artist_name = first_credit.get("name") if isinstance(first_credit, dict) else None
            if not isinstance(artist_name, str) or not artist_name.strip():
                artist_name = "Unknown Artist"
            songs.append({
                "name": title,
                "artist": {"name": artist_name},
                "musicbrainz_id": recording_id,
            })
        return songs
