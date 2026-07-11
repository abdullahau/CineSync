"""
Parse Wikidata SPARQL JSON bindings into per-title records. No 'error' key --
the driver carries fetch errors from the sparql layer. Results are keyed by
bare Q-id so the driver can map each back to a title_id via titles.wikidata_id.
"""

_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
_STATEMENT_PREFIX = "http://www.wikidata.org/entity/statement/"

# Prestige family by award-label prefix/substring. Label-matching (not family
# QIDs) is deliberate: the families are named very consistently on Wikidata, and
# an unmatched label fails VISIBLY (shows up as prestige=None) rather than
# silently returning zero the way a wrong QID would. Adding a family is one line.
_PRESTIGE_PREFIX = (
    ("Academy Award", "Oscars"),
    ("Primetime Emmy", "Primetime Emmy"),
    ("International Emmy", "International Emmy"),
    ("Golden Globe", "Golden Globe"),
    ("BAFTA", "BAFTA"),
    ("British Academy", "BAFTA"),
)
_PRESTIGE_CONTAINS = (
    ("Palme d'Or", "Cannes"),
    ("Golden Lion", "Venice"),
)


def tag_prestige(award_label):
    """Award label -> prestige family, or None if it isn't a tracked family."""
    if not award_label:
        return None
    for prefix, family in _PRESTIGE_PREFIX:
        if award_label.startswith(prefix):
            return family
    for needle, family in _PRESTIGE_CONTAINS:
        if needle in award_label:
            return family
    return None


def _val(row, key):
    cell = row.get(key)
    return cell.get("value") if cell else None


def _qid(uri):
    return uri.rsplit("/", 1)[-1] if uri else None


def parse_awards(bindings):
    """Award-statement rows -> {qid: [award dict, ...]}. Each award dict:
    statement_id, award_name, result, prestige, level, subject, year. `subject`
    is the person's name for level='person', None for level='title'. A title
    that won nothing simply won't appear as a key."""
    out = {}
    for row in bindings:
        qid = _qid(_val(row, "item"))
        if qid is None:
            continue
        level = _val(row, "level")
        year = _val(row, "year")
        award_name = _val(row, "awardLabel")
        out.setdefault(qid, []).append(
            {
                "statement_id": _statement_id(_val(row, "st")),
                "award_name": award_name,
                "result": _val(row, "result"),
                "prestige": tag_prestige(award_name),
                "level": level,
                "subject": _val(row, "subjectLabel") if level == "person" else None,
                "year": int(year) if year else None,
            }
        )
    return out


def _statement_id(uri):
    if not uri:
        return None
    if uri.startswith(_STATEMENT_PREFIX):
        return uri[len(_STATEMENT_PREFIX):]
    return uri


def parse_links(bindings):
    """Wikipedia-URL + RT-slug rows -> {qid: {'wikipedia_url', 'rt_slug'}}.
    Both OPTIONAL, so either may be None. One row per item (both fields are
    single-valued for a film/series), but we defensively keep the first
    non-null seen for each field in case of duplicate rows."""
    out = {}
    for row in bindings:
        qid = _qid(_val(row, "item"))
        if qid is None:
            continue
        rec = out.setdefault(qid, {"wikipedia_url": None, "rt_slug": None})
        if rec["wikipedia_url"] is None:
            rec["wikipedia_url"] = _val(row, "wikipediaArticle")
        if rec["rt_slug"] is None:
            rec["rt_slug"] = _val(row, "rtId")
    return out
