"""
Phase 8: blend per-source critic/audience scores into one weighted
critic_score, using the weights in config.yaml.

A missing source is neither treated as zero nor backfilled with an
average -- it's excluded entirely, and the remaining sources' weights
are rescaled (divided by their own sum) so they still sum to 1.0.
This preserves the RELATIVE trust between whichever sources you
actually have for a title, rather than fabricating a value for the
ones you don't.
"""

from cinesync.config_loader import load_config


def critic_score(scores: dict, weights: dict = None):
    """
    scores: {source_name: score_value} for whichever sources exist for
            this title -- e.g. from
            `SELECT source, score FROM external_scores WHERE title_id = ?`.
            Sources with no row at all simply aren't keys in this dict.
    weights: defaults to config.yaml's critic_score_weights.

    Returns None if none of the weighted sources have a score at all
    -- there's nothing to blend, and pretending otherwise (e.g.
    returning 0) would make an unscored title look like a bad one.
    """
    if weights is None:
        weights = load_config()["critic_score_weights"]

    available = {s: v for s, v in scores.items() if s in weights and v is not None}
    if not available:
        return None

    total_weight = sum(weights[s] for s in available)
    weighted_sum = sum(weights[s] * available[s] for s in available)
    return round(weighted_sum / total_weight, 2)
