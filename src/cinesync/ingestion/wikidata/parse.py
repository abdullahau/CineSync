"""
Assemble QLever bulk rows into DB records. The fetch layer (sparql.py) returns
cleaned dict rows keyed on imdb_id; here we filter to our titles, join the
separately-resolved labels, and tag prestige. Pure functions -- no network, no
DB -- so they're unit-testable against fixtures.
"""

# Prestige family by award-label prefix/substring. Label-matching (not family
# QIDs) is deliberate: the families are named very consistently on Wikidata, and
# an unmatched label fails VISIBLY (prestige=None) rather than silently. Adding a
# family is one line.
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


def assemble_spine(spine_rows, imdb_to_title):
    """Filter the global spine to our titles. Returns
    (url_by_title: {title_id: wikipedia_url}, rt_rows: [(title_id, rt_slug)]).
    First non-null value wins if an imdb_id maps to multiple Wikidata items."""
    url_by_title = {}
    rt_by_title = {}
    for row in spine_rows:
        title_id = imdb_to_title.get(row["imdb_id"])
        if title_id is None:
            continue
        if row.get("wikipedia_url") and title_id not in url_by_title:
            url_by_title[title_id] = row["wikipedia_url"]
        if row.get("rt_slug") and title_id not in rt_by_title:
            rt_by_title[title_id] = row["rt_slug"]
    rt_rows = list(rt_by_title.items())
    return url_by_title, rt_rows


def assemble_awards(stmt_rows, award_labels, person_labels, imdb_to_title):
    """Filter award statements to our titles, join labels, tag prestige. Returns
    title_awards tuples (title_id, statement_id, award_name, result, prestige,
    level, subject, year), deduped by (title_id, statement_id). `award_name`
    falls back to the award QID when Wikidata has no English label (the column is
    NOT NULL); `subject` is the person's name for level='person', else None."""
    seen = set()
    rows = []
    for s in stmt_rows:
        title_id = imdb_to_title.get(s["imdb_id"])
        if title_id is None:
            continue
        key = (title_id, s["statement_id"])
        if key in seen:
            continue
        seen.add(key)
        award_name = award_labels.get(s["award_qid"]) or s["award_qid"]
        subject = person_labels.get(s["person_qid"]) if s["level"] == "person" else None
        rows.append((
            title_id,
            s["statement_id"],
            award_name,
            s["result"],
            tag_prestige(award_name),
            s["level"],
            subject,
            s["year"],
        ))
    return rows
