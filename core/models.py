from django.db import models

class Song(models.Model):
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    musicbrainz_id = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.title} — {self.artist}"


class SongRequest(models.Model):
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default="Pending")

    def __str__(self):
        return f"{self.song} — {self.status}"
