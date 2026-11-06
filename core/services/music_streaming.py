#spotify api was select as we have yet to hear back from any of the other companies.
#preparing the class for music streaming to be filled out later, contact Spencer to get the API and Secret.

#adjustment to prevent collision with the queue
import sys
from pathlib import Path
_script_dir = str(Path(__file__).resolve().parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)


import os
import time
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv

#pull credentials from env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_file = BASE_DIR / ".env"

load_dotenv(env_file)

class SpotifyClient:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"

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
        #encode credentials for security
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def get_token(self) -> str:
        #retrieve existing token if its valid
        if self._access_token and time.time() < (self._expires_at - 60):
            return self._access_token

        #establish client credentials
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





#run directly to test
if __name__ == "__main__":
    print("Testing Spotify ")
    try:
        client = SpotifyClient()
        token = client.get_token()
        print(f"Auth Handshake: SUCCESS")
        print("Connected to Spotify successfully.")
    except Exception as e:
        print(f"Connection Failed: {e}")