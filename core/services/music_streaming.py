# spotify api was select as we have yet to hear back from any of the other companies.
# preparing the class for music streaming to be filled out later, contact Spencer to get the API and Secret.

# adjustment to prevent collision with the queue
import sys
from pathlib import Path

_script_dir = str(Path(__file__).resolve().parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)

import os
import time
import base64
import requests
from dotenv import load_dotenv

# pull credentials from env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_file = BASE_DIR / ".env"
load_dotenv(env_file)


class SpotifyClient:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"
    MB_API_BASE = "https://musicbrainz.org/ws/2"
    MB_HEADERS = {
        "User-Agent": "RhythmiQ/1.0.0 (contact: Shall053@odu.edu)",
        "Accept": "application/json",
    }

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self._access_token = None
        self._expires_at = 0

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET in .env"
            )

    def _get_auth_header(self) -> dict:
        # encode credentials for security
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def get_token(self) -> str:
        # retrieve existing token if its valid
        if self._access_token and time.time() < (self._expires_at - 60):
            return self._access_token

        # establish client credentials
        data = {"grant_type": "client_credentials"}
        response = requests.post(
            self.TOKEN_URL,
            headers=self._get_auth_header(),
            data=data,
            timeout=10,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Spotify auth failed [{response.status_code}]: {response.text}"
            )

        payload = response.json()
        self._access_token = payload.get("access_token")
        self._expires_at = time.time() + payload.get("expires_in", 3600)
        return self._access_token

    def _search_spotify(self, query: str) -> dict | None:
        # search single track using the api
        token = self.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": "track", "limit": 1}

        try:
            res = requests.get(
                f"{self.API_BASE}/search",
                headers=headers,
                params=params,
                timeout=10,
            )
            if res.status_code == 200:
                items = res.json().get("tracks", {}).get("items", [])
                return items[0] if items else None
        except requests.RequestException as e:
            print(f"Spotify Network Error: {e}")

        return None

    def _lookup_mbid_isrcs(self, mbid: str) -> list[str]:
        # fallback searching
        try:
            res = requests.get(
                f"{self.MB_API_BASE}/recording/{mbid.strip()}",
                headers=self.MB_HEADERS,
                params={"inc": "isrcs", "fmt": "json"},
                timeout=5,
            )
            if res.status_code == 200:
                return res.json().get("isrcs", [])
        except requests.RequestException as e:
            print(f"[MusicBrainz Fallback Error]: {e}")

        return []

    def resolve_song(self, mb_song: dict) -> dict | None:
        # accept the song info
        if not isinstance(mb_song, dict):
            return None

        # Support keys ("title", "artist", "id") with fallback 
        title = (mb_song.get("title") or mb_song.get("name") or "").strip()

        raw_artist = mb_song.get("artist")
        if isinstance(raw_artist, dict):
            artist_name = raw_artist.get("name", "").strip()
        elif isinstance(raw_artist, str):
            artist_name = raw_artist.strip()
        else:
            artist_name = ""

        mbid = (mb_song.get("id") or mb_song.get("musicbrainz_id") or "").strip()

        if not title:
            return None

        spotify_track = None

        # search with artist info 
        if artist_name and artist_name != "Unknown Artist":
            spotify_track = self._search_spotify(f'track:"{title}" artist:"{artist_name}"')

        # fallback using the recording UUID 
        if not spotify_track and mbid:
            for isrc in self._lookup_mbid_isrcs(mbid):
                spotify_track = self._search_spotify(f"isrc:{isrc}")
                if spotify_track:
                    break

        # loose text fallback
        if not spotify_track:
            loose_query = f"{title} {artist_name}" if artist_name and artist_name != "Unknown Artist" else title
            spotify_track = self._search_spotify(loose_query)

        if not spotify_track:
            return None

        return {
            **mb_song,  # Preserves id, title, artist, genre, BPM, vibe_characteristics, is_explicit
            "spotify_id": spotify_track["id"],
            "spotify_uri": spotify_track["uri"],
            "duration_ms": spotify_track.get("duration_ms"),
            "external_url": spotify_track.get("external_urls", {}).get("spotify"),
        }

    def get_track_browser_url(self, mb_song: dict) -> str | None:
        # get the URL to play it
        resolved = self.resolve_song(mb_song)
        if not resolved:
            return None
        return resolved.get("external_url")


# run directly to test
if __name__ == "__main__":
    import webbrowser

    client = SpotifyClient()
    print("=== MusicBrainz Payload -> Spotify Resolver Test ===")

    # Exact shape returned by your  method
    mock_selection = {
        "name": "Never Gonna Give You Up",
        "artist": {"name": "Rick Astley"},
        "musicbrainz_id": "2c8d3072-7325-443d-b98d-7d989b1031e4",
    }

    print(f"Input payload: {mock_selection}\n")
    resolved = client.resolve_song(mock_selection)

    if resolved:
        print("Matched")
        print(f"  • Title:          {resolved['name']}")
        print(f"  • Artist:         {resolved['artist']['name']}")
        print(f"  • MusicBrainz ID: {resolved['musicbrainz_id']}")
        print(f"  • Spotify URI:    {resolved['spotify_uri']}")
        print(f"  • Spotify Link:   {resolved['external_url']}")

        if resolved.get("external_url"):
            webbrowser.open(resolved["external_url"])
    else:
        print("Could not resolve song.")