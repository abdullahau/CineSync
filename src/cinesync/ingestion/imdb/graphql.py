import asyncio
import json
import random
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
    """curl_cffi AsyncSession with Chrome TLS impersonation -- IMDb's GraphQL
    edge blocks non-browser fingerprints. Impersonation is set once here rather
    than per request."""
    return requests.AsyncSession(impersonate="chrome")


def _batch_element(result):
    """One batched sub-result -> fetch_title's contract: {'title': raw} | {'error'}."""
    if not isinstance(result, dict):
        return {"error": f"unexpected batch element: {str(result)[:200]}"}
    if result.get("errors"):
        return {"error": json.dumps(result["errors"])[:300]}
    title = (result.get("data") or {}).get("title")
    return {"title": title} if title else {"error": "no title in response"}


async def fetch_enrichment_batch(session, imdb_id, *, max_retries, timeout):
    """Fetch storyline + worldwide ratings histogram for one title in a SINGLE
    batched GraphQL POST (a JSON array of the persisted Title_Storyline op and
    the inline TitleRatingsHistogram op). Returns

        {"storyline": {'title'|'error'}, "histogram": {'title'|'error'}}

    where each side follows the {'title'|'error'} contract, so parse.parse and
    parse_ratings_histogram apply unchanged. HTTP-level failures (403/429/5xx)
    retry the WHOLE batch with backoff; a per-op GraphQL error is reported for
    that op only, so one side can succeed while the other fails. Batch reply is
    array-ordered to the request, so index 0=storyline, 1=histogram.

    Network + retry only (max_retries/timeout come from rate_limiting.imdb via
    the driver); steady-state pacing is the caller's AsyncRateGate."""
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
    for attempt in range(max_retries):
        try:
            r = await session.post(ENDPOINT, headers=HEADERS, data=body, timeout=timeout)
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
                await asyncio.sleep((2**attempt) + random.uniform(0, 1))
                continue
            err = {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
            return {"storyline": dict(err), "histogram": dict(err)}
        except Exception as e:
            last = str(e)
            await asyncio.sleep((2**attempt) + random.uniform(0, 1))
    err = {"error": f"failed after {max_retries} retries: {last}"}
    return {"storyline": dict(err), "histogram": dict(err)}
