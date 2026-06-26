"""
Exponential time-decay weighting for recency-aware taste modeling.

Used anywhere a historical watch_events row needs to count more if
it's recent and less if it's old:
  - Phase 4's LightGBM `sample_weight` argument (combines naturally
    with rewatch-as-repeated-evidence: a recently-rewatched title
    contributes multiple high-weight rows)
  - Phase 9's taste-centroid calculation behind personal_fit and
    novelty scoring

Recency is a HALF-LIFE, not a hard cutoff: a rating's weight halves
every `half_life_days`, fading smoothly rather than being discarded
the moment it crosses some arbitrary date boundary. A lifetime
favorite from 5 years ago still counts -- just for very little -- so
there's no sparse-data cliff the way a hard "only the last N days"
window would create.
"""

from datetime import date, datetime

# Human-friendly presets -> half-life in days. Pass either one of
# these strings or a raw number of days to recency_weight()/
# resolve_half_life() for finer control than the presets offer.
# "lifetime" doesn't literally disable decay (true infinity isn't a
# valid divisor) -- 100 years is functionally flat at this project's
# timescale, which has the same practical effect.
RECENCY_PRESETS = {
    "2d": 2,
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "lifetime": 36500,
}


def resolve_half_life(recency_half_life) -> float:
    """Accepts a preset string ('2w') or a raw number of days (45)."""
    if isinstance(recency_half_life, (int, float)):
        return float(recency_half_life)
    try:
        return float(RECENCY_PRESETS[recency_half_life])
    except KeyError:
        raise ValueError(
            f"Unknown recency preset {recency_half_life!r}. "
            f"Use one of {list(RECENCY_PRESETS)} or pass a number of days."
        )


def recency_weight(watched_date: str, half_life_days, as_of: date = None) -> float:
    """
    weight = 0.5 ** (days_since_watched / half_life_days)

    A rating from exactly one half-life ago counts for 0.5x; two
    half-lives ago, 0.25x; and so on -- smooth decay, not a cliff.

    half_life_days may be a preset string ('2w') or a raw number.
    watched_date is read as just the date portion (first 10 chars),
    so it tolerates either 'YYYY-MM-DD' or a full timestamp.
    """
    half_life = resolve_half_life(half_life_days)
    as_of = as_of or date.today()
    watched = datetime.strptime(watched_date[:10], "%Y-%m-%d").date()
    days_since = max((as_of - watched).days, 0)
    return 0.5 ** (days_since / half_life)
