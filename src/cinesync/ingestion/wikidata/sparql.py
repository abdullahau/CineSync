"""
Wikidata SPARQL fetch layer -- network + retry only, parsing lives in
wikidata_parser. Mirrors imdb/graphql.py's contract: each fetch returns
{'bindings': [...]} on success or {'error': str} on failure.

Keyed on Wikidata Q-ids (which titles already carry in titles.wikidata_id), NOT
on IMDb P345: we have the Q-id, so `VALUES ?film { wd:Q... }` is a direct lookup
that sidesteps the movie/tv IMDb-namespace ambiguity and the one-imdb-to-many-
items case.

Two queries, both batched over the same VALUES block:
  fetch_awards() -> one row per award statement (title- and person-level)
  fetch_links()  -> Wikipedia article URL + Rotten Tomatoes slug (single-valued)

WDQS etiquette: single-threaded, ~1 req/s, 60s server-side timeout, MANDATORY
descriptive User-Agent. Config lives under the `wikidata` block; DEFAULTS below
apply if it's absent so the pipeline runs before config.yaml is updated.
"""

import requests
from cinesync.config_loader import load_config
from cinesync.utils.net import paced_request
from cinesync.ingestion.wikidata import USER_AGENT

# Endpoint lives in code, not config (config carries only pacing knobs). WDQS
# requires a descriptive User-Agent (bare requests UA gets blocked); its contact
# email comes from EMAIL env via the package USER_AGENT. Pacing/batch_size come
# from rate_limiting.wikidata via _cfg().
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT}


def _cfg():
    """rate_limiting.wikidata: min_interval/max_retries/timeout (used by
    paced_request) plus batch_size (read by the driver)."""
    return load_config()["rate_limiting"]["wikidata"]


def new_session():
    return requests.Session()


def _values_clause(qids):
    """`VALUES ?item { wd:Q1 wd:Q2 ... }` for a batch of bare Q-ids."""
    return "VALUES ?item { " + " ".join(f"wd:{q}" for q in qids) + " }"


# The film item is bound as ?item so we can map each row back to its title.
# Awards attach in two places: directly on the film (?item), and on a person
# (?subject) with a pq:P1686 "for work" qualifier pointing at the film. The
# nominated branch excludes wins per-subject (some editors log a win under both
# P166 and P1411) via FILTER NOT EXISTS -- scoped to the same subject+award so
# one person's win never cancels another's nomination in the same category.
_AWARDS_TEMPLATE = """
SELECT DISTINCT ?item ?result ?st ?awardLabel ?subject ?subjectLabel ?level (YEAR(?time) AS ?year)
WHERE {{
  {values}
  {{
    {{ ?item p:P166 ?st . ?st ps:P166 ?award . BIND(?item AS ?subject) }}
    UNION
    {{ ?subject p:P166 ?st . ?st ps:P166 ?award ; pq:P1686 ?item . }}
    OPTIONAL {{ ?st pq:P585 ?time . }}
    BIND("won" AS ?result)
  }}
  UNION
  {{
    {{
      ?item p:P1411 ?st . ?st ps:P1411 ?award . BIND(?item AS ?subject)
      FILTER NOT EXISTS {{ ?item wdt:P166 ?award . }}
    }}
    UNION
    {{
      ?subject p:P1411 ?st . ?st ps:P1411 ?award ; pq:P1686 ?item .
      FILTER NOT EXISTS {{ ?subject p:P166 ?w . ?w ps:P166 ?award ; pq:P1686 ?item . }}
    }}
    OPTIONAL {{ ?st pq:P585 ?time . }}
    BIND("nominated" AS ?result)
  }}
  ?award rdfs:label ?awardLabel . FILTER(LANG(?awardLabel) = "en")
  BIND(IF(?subject = ?item, "title", "person") AS ?level)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""

# Single-valued fields; kept out of the award query so the per-award fan-out
# doesn't multiply them. P1258 is the Rotten Tomatoes ID ('m/...'/'tv/...').
_LINKS_TEMPLATE = """
SELECT ?item ?wikipediaArticle ?rtId
WHERE {{
  {values}
  OPTIONAL {{
    ?wikipediaArticle schema:about ?item ;
                      schema:isPartOf <https://en.wikipedia.org/> .
  }}
  OPTIONAL {{ ?item wdt:P1258 ?rtId . }}
}}
"""


def _query(session, sparql):
    """POST one SPARQL query via the shared paced_request (retry/backoff/pacing
    from rate_limiting.wikidata). Returns {'bindings': [...]} or {'error': str}
    -- a non-200 or malformed body becomes an error the driver can log-and-skip."""
    try:
        r = paced_request(
            session, ENDPOINT, service="wikidata", method="POST",
            data={"query": sparql}, headers=HEADERS,
        )
    except Exception as e:
        return {"error": str(e)[:300]}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    try:
        return {"bindings": r.json()["results"]["bindings"]}
    except Exception as e:
        return {"error": f"bad SPARQL JSON: {str(e)[:200]}"}


def fetch_awards(session, qids):
    """Award statements for a batch of Q-ids. {'bindings'|'error'}."""
    return _query(session, _AWARDS_TEMPLATE.format(values=_values_clause(qids)))


def fetch_links(session, qids):
    """Wikipedia URL + RT slug for a batch of Q-ids. {'bindings'|'error'}."""
    return _query(session, _LINKS_TEMPLATE.format(values=_values_clause(qids)))
