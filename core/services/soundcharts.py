import requests

from Rhythmiq import settings

class SoundchartsClient:
    BASE_URL = "https://customer.api.soundcharts.com"

    def __init__(self):
        # Sandbox uses these fixed literal values — not per-app credentials
        self.headers = {
            "x-app-id": settings.SOUNDCHARTS_APP_ID,
            "x-api-key": settings.SOUNDCHARTS_API_KEY,
        }

    def search_songs(self, query):
        resp = requests.get(
            f"{self.BASE_URL}/api/v2/song/search/{query}",
            headers=self.headers,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])