import json
import random
import time
from urllib.parse import quote
from curl_cffi import requests

ENDPOINT = "https://caching.graphql.imdb.com/"
OPERATION = "Title_Storyline"
# SHA-256 of IMDb's Title_Storyline persisted query, baked into their JS bundle.
# Same for every title; refresh from DevTools if you start getting
# "PersistedQueryNotFound".
SHA256 = "bbf29ee4ceeefcf2d0825e0e57e3821aa2e11166b7cf820e1b40fb21095d7b08"

HEADERS = {
    "accept": "application/graphql+json, application/json",
    "content-type": "application/json",
    "referer": "https://www.imdb.com/",
    "origin": "https://www.imdb.com",
    "x-imdb-client-name": "imdb-web-next-localized",
    "x-imdb-user-country": "US",
    "x-imdb-user-language": "en-US",
}

# Worldwide ratings histogram. Sent as an INLINE query (not a persisted-query
# hash) on purpose: the worldwide breakdown is server-side rendered on IMDb and
# never fires as a client request, so there's no hash to copy. The only
# client-side histogram request (TitleFilteredHistogramData) is a *per-country*
# operation driven by the x-imdb-user-country header -- not what we want.
RATINGS_OPERATION = "TitleRatingsHistogram"
RATINGS_QUERY = (
    "query TitleRatingsHistogram($id: ID!) { "
    "title(id: $id) { id "
    "ratingsSummary { aggregateRating voteCount } "
    "aggregateRatingsBreakdown { histogram { histogramValues { rating voteCount } } } "
    "} }"
)


def new_session():
    return requests.Session()


def build_url(imdb_id):
    variables = {
        "isInMachineTranslateWeblab": True,
        "locale": "en-US",
        "titleId": imdb_id,
    }
    extensions = {"persistedQuery": {"sha256Hash": SHA256, "version": 1}}
    return (
        f"{ENDPOINT}?operationName={OPERATION}"
        f"&variables={quote(json.dumps(variables, separators=(',', ':')))}"
        f"&extensions={quote(json.dumps(extensions, separators=(',', ':')))}"
    )


def fetch_title(session, imdb_id, retries=4):
    """Returns {'title': <raw title json>} on success or {'error': str} on
    failure. Network + retry only -- parsing lives in imdb_parser."""
    url = build_url(imdb_id)
    last = ""
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, impersonate="chrome", timeout=25)
            if r.status_code == 200:
                data = r.json()
                if data.get("errors"):
                    return {"error": json.dumps(data["errors"])[:300]}
                title = (data.get("data") or {}).get("title")
                return {"title": title} if title else {"error": "no title in response"}
            if r.status_code in (403, 429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            last = str(e)
            time.sleep((2**attempt) + random.uniform(0, 1))
    return {"error": f"failed after {retries} retries: {last}"}


def _batch_element(result):
    """One batched sub-result -> fetch_title's contract: {'title': raw} | {'error'}."""
    if not isinstance(result, dict):
        return {"error": f"unexpected batch element: {str(result)[:200]}"}
    if result.get("errors"):
        return {"error": json.dumps(result["errors"])[:300]}
    title = (result.get("data") or {}).get("title")
    return {"title": title} if title else {"error": "no title in response"}


def fetch_enrichment_batch(session, imdb_id, retries=4):
    """Fetch storyline + worldwide ratings histogram for one title in a SINGLE
    batched GraphQL POST (a JSON array of the persisted Title_Storyline op and
    the inline TitleRatingsHistogram op). Returns

        {"storyline": {'title'|'error'}, "histogram": {'title'|'error'}}

    where each side follows fetch_title's contract, so imdb_parser.parse and
    parse_ratings_histogram apply unchanged. HTTP-level failures (403/429/5xx)
    retry the WHOLE batch with backoff; a per-op GraphQL error is reported for
    that op only, so one side can succeed while the other fails. Batch reply is
    array-ordered to the request, so index 0=storyline, 1=histogram."""
    ops = [
        {
            "operationName": OPERATION,
            "variables": {
                "isInMachineTranslateWeblab": True,
                "locale": "en-US",
                "titleId": imdb_id,
            },
            "extensions": {"persistedQuery": {"sha256Hash": SHA256, "version": 1}},
        },
        {
            "operationName": RATINGS_OPERATION,
            "query": RATINGS_QUERY,
            "variables": {"id": imdb_id},
        },
    ]
    body = json.dumps(ops)
    last = ""
    for attempt in range(retries):
        try:
            r = session.post(
                ENDPOINT, headers=HEADERS, data=body, impersonate="chrome", timeout=25
            )
            if r.status_code == 200:
                data = r.json()
                if not isinstance(data, list) or len(data) != 2:
                    err = {"error": f"bad batch shape: {str(data)[:200]}"}
                    return {"storyline": dict(err), "histogram": dict(err)}
                return {
                    "storyline": _batch_element(data[0]),
                    "histogram": _batch_element(data[1]),
                }
            if r.status_code in (403, 429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            err = {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
            return {"storyline": dict(err), "histogram": dict(err)}
        except Exception as e:
            last = str(e)
            time.sleep((2**attempt) + random.uniform(0, 1))
    err = {"error": f"failed after {retries} retries: {last}"}
    return {"storyline": dict(err), "histogram": dict(err)}


def fetch_ratings_histogram(session, imdb_id, retries=4):
    """Worldwide IMDb ratings histogram via an inline (non-persisted) GraphQL
    POST. Returns {'title': <raw title json>} (carrying ratingsSummary +
    aggregateRatingsBreakdown) on success, or {'error': str}. Same contract,
    endpoint, headers, and backoff as fetch_title -- network + retry only,
    parsing lives in imdb_parser."""
    body = json.dumps(
        {
            "operationName": RATINGS_OPERATION,
            "query": RATINGS_QUERY,
            "variables": {"id": imdb_id},
        }
    )
    last = ""
    for attempt in range(retries):
        try:
            r = session.post(
                ENDPOINT, headers=HEADERS, data=body, impersonate="chrome", timeout=25
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("errors"):
                    return {"error": json.dumps(data["errors"])[:300]}
                title = (data.get("data") or {}).get("title")
                return {"title": title} if title else {"error": "no title in response"}
            if r.status_code in (403, 429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            last = str(e)
            time.sleep((2**attempt) + random.uniform(0, 1))
    return {"error": f"failed after {retries} retries: {last}"}
