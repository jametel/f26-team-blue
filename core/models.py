from django.conf import settings
from django.db import models
from django.contrib.auth.models import User

class Song(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    genre = models.CharField(max_length=100, null=True, blank=True)
    BPM = models.IntegerField(null=True, blank=True)
    is_explicit = models.BooleanField(null=True, blank=True)
    musicbrainz_id = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.title} — {self.artist}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user}"

class Venue(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    qr_code = models.FileField(upload_to="qr_codes/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class SongRequest(models.Model):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLAYED = "PLAYED"
    id = models.AutoField(primary_key=True)
    user_id = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)
    venue_id = models.ForeignKey(Venue, on_delete=models.SET_NULL, null=True, blank=True)
    song_id = models.ForeignKey(Song, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="song_requests")
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=[
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("PLAYED", "Played"),
    ], default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id} — {self.song_id} — {self.status}"

class venueGenreFilter(models.Model):
    id = models.AutoField(primary_key=True)
    venue_id = models.ForeignKey(Venue, on_delete=models.CASCADE)
    genre = models.CharField(max_length=100)
    is_allowed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('venue_id', 'genre')

    def __str__(self):
        return f"{self.venue_id} — {self.genre}"

class VenueSongBlacklist(models.Model):
    id = models.AutoField(primary_key=True)
    venue_id = models.ForeignKey(Venue, on_delete=models.CASCADE)
    song_id = models.ForeignKey(Song, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('venue_id', 'song_id')

    def __str__(self):
        return f"{self.venue_id} — {self.song_id}"

class Queue(models.Model):
    id = models.AutoField(primary_key=True)
    venue_id = models.ForeignKey(Venue, on_delete=models.CASCADE)
    song_request_id = models.ForeignKey(SongRequest, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

class Payments(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
    ]
    id = models.AutoField(primary_key=True)
    user_id = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    song_request_id = models.ForeignKey(SongRequest, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.userID} — {self.venueID} — {self.amount}"

class Refunds(models.Model):
    REFUND_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
    ]
    id = models.AutoField(primary_key=True)
    payment_id = models.ForeignKey(Payments, on_delete=models.CASCADE)
    song_request_id = models.ForeignKey(SongRequest, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payment_id} — {self.reason}"

class Overrides(models.Model):
    id = models.AutoField(primary_key=True)
    song_request_id = models.ForeignKey(SongRequest, on_delete=models.CASCADE)
    staff_user_id = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.song_request_id} — {self.staff_user_id} — {self.reason}"
