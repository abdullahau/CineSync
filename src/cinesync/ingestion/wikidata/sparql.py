"""
Wikidata bulk fetch via QLever (https://qlever.dev) -- NOT the public WDQS,
which times out / crawls at 70k-title scale. QLever answers a single global scan
over all films in ~5s.

Strategy (validated against the live endpoint):
  - Two *global* scans, keyed on IMDb ID (P345, tt-prefixed): the `spine`
    (imdb_id -> qid, RT slug, Wikipedia URL) and the raw `award statements`
    (imdb_id -> statement, result, level, award QID, person QID, year). Both
    return QIDs, NOT labels -- joining labels *inside* the statement scan is what
    made it time out.
  - Labels are resolved separately in cheap batched `VALUES` queries (award names
    + person names), keyed on the small set of QIDs that actually appear.

The driver filters the global results down to our titles by imdb_id and does the
label join + prestige tagging in parse.py. Keying on imdb_id (tt-unique) is
unambiguous -- the movie/tv namespace collision that forced Q-id-first elsewhere
only affects TMDB IDs, not IMDb IDs.

Everything goes through net.paced_request (plain requests, POST sparql-query,
TSV out); pacing/retry/timeout come from rate_limiting.wikidata.
"""

import re

from cinesync.config_loader import load_config
from cinesync.utils.net import paced_request
from cinesync.ingestion.wikidata import USER_AGENT

# A real Wikidata entity QID. Some P166/P1411 values are "somevalue" blank nodes,
# skolemized as `.../.well-known/genid/...` IRIs -- not QIDs, no label, and
# `wd:<that>` is invalid SPARQL. We filter those out.
_QID_RE = re.compile(r"^Q\d+$")

ENDPOINT = "https://qlever.dev/api/wikidata"
HEADERS = {
    "Accept": "text/tab-separated-values",
    "Content-type": "application/sparql-query",
    "User-Agent": USER_AGENT,
}

_ENTITY = "http://www.wikidata.org/entity/"
_STATEMENT = "http://www.wikidata.org/entity/statement/"

_SPINE_QUERY = """
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>
SELECT ?imdbId ?item ?rtId ?enwiki WHERE {
  ?item wdt:P345 ?imdbId . FILTER(STRSTARTS(?imdbId, "tt"))
  OPTIONAL { ?item wdt:P1258 ?rtId . }
  OPTIONAL { ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
}
"""

# Won + nominated-excluding-won, film-level and person-level (P1686 "for work").
# MINUS (not FILTER NOT EXISTS) -- semantically identical, runs on any engine.
# QIDs only, no label joins (those are resolved separately in fetch_labels).
_AWARDS_QUERY = """
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p:   <http://www.wikidata.org/prop/>
PREFIX ps:  <http://www.wikidata.org/prop/statement/>
PREFIX pq:  <http://www.wikidata.org/prop/qualifier/>
SELECT ?imdbId ?st ?result ?level ?award ?person ?year WHERE {
  ?film wdt:P345 ?imdbId . FILTER(STRSTARTS(?imdbId, "tt"))
  {
    { ?film p:P166 ?st . ?st ps:P166 ?award . BIND("title" AS ?level) }
    UNION
    { ?person p:P166 ?st . ?st ps:P166 ?award ; pq:P1686 ?film . BIND("person" AS ?level) }
    BIND("won" AS ?result)
  }
  UNION
  {
    { ?film p:P1411 ?st . ?st ps:P1411 ?award . BIND("title" AS ?level)
      MINUS { ?film wdt:P166 ?award . } }
    UNION
    { ?person p:P1411 ?st . ?st ps:P1411 ?award ; pq:P1686 ?film . BIND("person" AS ?level)
      MINUS { ?person p:P166 ?w . ?w ps:P166 ?award ; pq:P1686 ?film . } }
    BIND("nominated" AS ?result)
  }
  OPTIONAL { ?st pq:P585 ?time . BIND(YEAR(?time) AS ?year) }
}
"""

_LABELS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?q ?qLabel WHERE {{
  VALUES ?q {{ {values} }}
  ?q rdfs:label ?qLabel . FILTER(LANG(?qLabel) = "en")
}}
"""


def _cfg():
    return load_config()["rate_limiting"]["wikidata"]


def new_session():
    import requests
    return requests.Session()


def _cell(c):
    """One SPARQL-TSV cell -> plain value. IRIs come `<...>`; literals come
    `"..."` optionally with an `@lang`/`^^<type>` suffix (stripped)."""
    c = c.strip()
    if not c:
        return None
    if c[0] == "<" and c[-1] == ">":
        return c[1:-1]
    if c[0] == '"':
        return c[1:c.rfind('"')]
    return c


def _parse_tsv(text):
    """QLever TSV -> list of dicts keyed by header name (leading '?' stripped)."""
    lines = text.split("\n")
    if not lines or not lines[0].strip():
        return []
    cols = [h.strip().lstrip("?") for h in lines[0].rstrip("\n").split("\t")]
    out = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cells = ln.rstrip("\n").split("\t")
        out.append({cols[i]: _cell(cells[i]) if i < len(cells) else None
                    for i in range(len(cols))})
    return out


def _qid(uri):
    return uri[len(_ENTITY):] if uri and uri.startswith(_ENTITY) else uri


def _statement_id(uri):
    return uri[len(_STATEMENT):] if uri and uri.startswith(_STATEMENT) else uri


def _post(session, query):
    """POST one SPARQL query to QLever, return parsed TSV rows. Raises on a
    non-200 (the driver wraps the whole pass, so a failure aborts the refresh
    rather than silently half-writing)."""
    r = paced_request(
        session, ENDPOINT, service="wikidata", method="POST",
        data=query.encode("utf-8"), headers=HEADERS,
    )
    r.raise_for_status()
    return _parse_tsv(r.text)


def fetch_spine(session):
    """All tt-titles: [{imdb_id, qid, rt_slug, wikipedia_url}] (one row per
    Wikidata item; an imdb_id with multiple items yields multiple rows)."""
    return [
        {
            "imdb_id": row["imdbId"],
            "qid": _qid(row["item"]),
            "rt_slug": row.get("rtId"),
            "wikipedia_url": row.get("enwiki"),
        }
        for row in _post(session, _SPINE_QUERY)
    ]


def fetch_award_statements(session):
    """All award statements (QIDs, no labels):
    [{imdb_id, statement_id, result, level, award_qid, person_qid, year}]."""
    out = []
    for row in _post(session, _AWARDS_QUERY):
        year = row.get("year")
        out.append({
            "imdb_id": row["imdbId"],
            "statement_id": _statement_id(row["st"]),
            "result": row["result"],
            "level": row["level"],
            "award_qid": _qid(row.get("award")),
            "person_qid": _qid(row.get("person")),
            "year": int(year) if year and year.isdigit() else None,
        })
    return out


def fetch_labels(session, qids):
    """{qid: en_label} for a set of QIDs, resolved in label_batch_size chunks.
    QIDs with no English label simply don't appear in the result."""
    qids = [q for q in dict.fromkeys(qids) if q and _QID_RE.match(q)]  # dedup; drop falsy + non-QID (genid) nodes
    size = _cfg()["label_batch_size"]
    labels = {}
    for i in range(0, len(qids), size):
        chunk = qids[i:i + size]
        values = " ".join(f"wd:{q}" for q in chunk)
        query = "PREFIX wd: <http://www.wikidata.org/entity/>\n" + \
                _LABELS_QUERY.format(values=values)
        for row in _post(session, query):
            labels[_qid(row["q"])] = row["qLabel"]
    return labels
