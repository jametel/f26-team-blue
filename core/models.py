from django.conf import settings
from django.db import models

class Song(models.Model):
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    musicbrainz_id = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.title} — {self.artist}"


class SongRequest(models.Model):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    PLAYED = "Played"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (PLAYED, "Played"),
    ]

    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="song_requests",
    )
    # Anonymous patrons are tracked by their Django session instead of an account.
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)

    def __str__(self):
        return f"{self.song} — {self.status}"
