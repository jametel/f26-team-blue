from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import SongFeatures


@dataclass(frozen=True)
class FeatureData:
    source: str
    genre: str | None = None
    bpm: int | None = None
    mood: str | None = None
    energy: Decimal | None = None
    is_explicit: bool | None = None
    confidence: Decimal | None = None


def get_song_features(song):
    return SongFeatures.objects.filter(song=song).first()


@transaction.atomic
def refresh_song_features(song, provider):
    """Fetch a provider's features, keeping the cache if none are available."""
    data = provider.fetch(song)
    if data is None:
        return get_song_features(song)
    features, _ = SongFeatures.objects.get_or_create(song=song)
    for field in ('source', 'genre', 'bpm', 'mood', 'energy', 'is_explicit', 'confidence'):
        setattr(features, field, getattr(data, field))
    features.refreshed_at = timezone.now()
    features.full_clean()
    features.save()
    return features
