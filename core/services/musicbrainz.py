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
        songs = []
        for rec in recordings:
            if not isinstance(rec, dict):
                continue
            recording_id, title = rec.get("id"), rec.get("title")
            if not isinstance(recording_id, str) or not recording_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            songs.append({
                "id": recording_id.strip(),
                "title": title.strip(),
                "artist": self._artist_name(rec),
                "genre": self._top_genre(rec),
                "BPM": None,                   # not provided by MusicBrainz
                "vibe_characteristics": None,  # not provided by MusicBrainz
                "is_explicit": self._is_explicit(rec),
            })
        return songs

    @staticmethod
    def _artist_name(rec):
        credits = rec.get("artist-credit")
        first = credits[0] if isinstance(credits, list) and credits else None
        name = first.get("name") if isinstance(first, dict) else None
        if not isinstance(name, str) or not name.strip():
            return "Unknown Artist"
        return name.strip()

    @staticmethod
    def _top_genre(rec):
        """Pick the most-voted tag as the genre, or None if there are no tags."""
        tags = rec.get("tags")
        if not isinstance(tags, list):
            return None
        valid = [t for t in tags if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()]
        if not valid:
            return None
        best = max(valid, key=lambda t: t.get("count", 0) if isinstance(t.get("count"), int) else 0)
        return best["name"].strip()

    @staticmethod
    def _is_explicit(rec):
        """MusicBrainz has no explicit flag; infer from the disambiguation text."""
        disambiguation = rec.get("disambiguation")
        return isinstance(disambiguation, str) and "explicit" in disambiguation.lower()