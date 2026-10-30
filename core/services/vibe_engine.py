from dataclasses import dataclass

from core.models import SongDecision, VenueConfig, VenueSongBlacklist, venueGenreFilter
from core.services.song_features import get_song_features


@dataclass(frozen=True)
class VibeDecision:
    outcome: str
    reasons: list[str]
    inputs: dict


def evaluate_request(venue, song):
    config = VenueConfig.objects.filter(venue=venue).first() or VenueConfig(venue=venue)
    features = get_song_features(song)
    trusted = features is not None and features.source != 'legacy-unverified'
    genre = features.genre.strip().casefold() if trusted and features.genre else None
    bpm = features.bpm if trusted and features.bpm and features.bpm > 0 else None
    explicit = features.is_explicit if trusted else None

    filters = list(venueGenreFilter.objects.filter(venue_id=venue).values_list('genre', 'is_allowed'))
    allowed = {name.strip().casefold() for name, is_allowed in filters if is_allowed}
    blocked = {name.strip().casefold() for name, is_allowed in filters if not is_allowed}
    blacklisted = VenueSongBlacklist.objects.filter(venue_id=venue, song_id=song).exists()
    inputs = {
        'allow_explicit': config.allow_explicit,
        'min_bpm': config.min_bpm,
        'max_bpm': config.max_bpm,
        'unknown_policy': config.unknown_policy,
        'allowed_genres': sorted(allowed),
        'blocked_genres': sorted(blocked),
        'blacklisted': blacklisted,
        'genre': genre,
        'bpm': bpm,
        'is_explicit': explicit,
        'source': features.source if features else None,
        'confidence': str(features.confidence) if features and features.confidence is not None else None,
        'refreshed_at': features.refreshed_at.isoformat() if features and features.refreshed_at else None,
    }
    rejected = []
    unknown = []
    if blacklisted:
        rejected.append('song_blacklisted')
    if not config.allow_explicit:
        if explicit is True:
            rejected.append('explicit_content')
        elif explicit is None:
            unknown.append('explicit_unknown')
    if allowed or blocked:
        if not genre:
            unknown.append('genre_unknown')
        elif genre in blocked or (allowed and genre not in allowed):
            rejected.append('genre_not_allowed')
    if config.min_bpm is not None or config.max_bpm is not None:
        if bpm is None:
            unknown.append('bpm_unknown')
        elif ((config.min_bpm is not None and bpm < config.min_bpm)
              or (config.max_bpm is not None and bpm > config.max_bpm)):
            rejected.append('bpm_out_of_range')

    if rejected:
        return VibeDecision(SongDecision.Outcome.REJECT, rejected, inputs)
    if unknown:
        policy = config.unknown_policy
        if policy not in SongDecision.Outcome.values:
            policy = SongDecision.Outcome.REVIEW
        return VibeDecision(policy, unknown, inputs)
    return VibeDecision(SongDecision.Outcome.ACCEPT, [], inputs)


def record_decision(venue, song, decision, song_request=None):
    return SongDecision.objects.create(
        venue=venue, song=song, request=song_request,
        outcome=decision.outcome, reasons=decision.reasons, inputs=decision.inputs,
    )
