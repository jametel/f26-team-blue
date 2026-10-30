from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

class Song(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    musicbrainz_id = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.title} — {self.artist}"


class SongFeatures(models.Model):
    song = models.OneToOneField(Song, on_delete=models.CASCADE, related_name='features')
    genre = models.CharField(max_length=100, null=True, blank=True)
    bpm = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    mood = models.CharField(max_length=100, null=True, blank=True)
    energy = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True,
                                 validators=[MinValueValidator(0), MaxValueValidator(1)])
    is_explicit = models.BooleanField(null=True, blank=True)
    source = models.CharField(max_length=100)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True,
                                     validators=[MinValueValidator(0), MaxValueValidator(1)])
    refreshed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Features for {self.song.title}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user}"

class Venue(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="owned_venues")
    staff = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="staff_venues")
    qr_code = models.FileField(upload_to="qr_codes/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"{slugify(self.name)[:80] or 'venue'}-{uuid4().hex[:8]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class VenueConfig(models.Model):
    class UnknownPolicy(models.TextChoices):
        REVIEW = "REVIEW", "Staff review"
        ACCEPT = "ACCEPT", "Accept"
        REJECT = "REJECT", "Reject"

    venue = models.OneToOneField(Venue, on_delete=models.CASCADE, related_name="config")
    min_bpm = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    max_bpm = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    allow_explicit = models.BooleanField(default=False)
    unknown_policy = models.CharField(max_length=10, choices=UnknownPolicy.choices,
                                      default=UnknownPolicy.REVIEW)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_bpm__isnull=True) | models.Q(min_bpm__gte=1),
                name="venue_min_bpm_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_bpm__isnull=True) | models.Q(max_bpm__gte=1),
                name="venue_max_bpm_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(min_bpm__isnull=True) | models.Q(max_bpm__isnull=True)
                          | models.Q(min_bpm__lte=models.F("max_bpm")),
                name="venue_bpm_range_valid",
            ),
        ]

    def __str__(self):
        return f"Settings for {self.venue}"

class SongRequest(models.Model):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLAYED = "PLAYED"
    id = models.AutoField(primary_key=True)
    user_id = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)
    venue_id = models.ForeignKey(Venue, on_delete=models.PROTECT, null=True, blank=True)
    song_id = models.ForeignKey(Song, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="song_requests")
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    legacy_unassigned = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=[
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("PLAYED", "Played"),
    ], default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(venue_id__isnull=False) | models.Q(legacy_unassigned=True),
                name="request_has_venue_or_is_legacy",
            ),
        ]

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
