"""
Stage B: fetch a title's Plot section from English Wikipedia -- ONE TextExtracts
request per title (whole article as PLAIN TEXT), sliced locally to the Plot
section.

Why one call (was two): the old approach listed the article's sections, then
fetched the plot section's HTML -- two round trips per title, and the driver ran
them sequentially at 2 req/s (~15h for 55k titles). TextExtracts returns the
whole article as plain text in a single request; with `exsectionformat=wiki`,
headings come through as `== Plot ==`, so we slice by heading level -- no HTML
parsing, half the requests, and a small plain-text payload (vs ~1 MB of article
HTML). Combined with async concurrency in the driver, ~10-20x faster.

Async so the driver can run many titles concurrently (capped by an AsyncRateGate
+ Semaphore). Contract unchanged: {'plot': text|None, 'error': str|None} --
a plotless article is a terminal success (error NULL, not retried); a
network/API failure preserves any existing text (error set, retried next run).
"""

import re
from urllib.parse import unquote
import curl_cffi.requests as requests
from cinesync.utils.net import paced_request_async
from cinesync.ingestion.wikidata import USER_AGENT

ENDPOINT = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": USER_AGENT}

# Plot-section headings vary across articles; check them all (lowercased).
PLOT_HEADINGS = {"plot", "plot summary", "synopsis", "premise", "plot synopsis"}

# A wikitext heading line as TextExtracts emits it: `== Plot ==`, `=== Season 1 ===`.
_HEADING = re.compile(r"(?m)^(={2,6})\s*(.+?)\s*\1\s*$")


def new_session():
    return requests.AsyncSession()


def _title_from_url(wikipedia_url):
    return unquote(wikipedia_url.rsplit("/", 1)[-1])


def slice_plot(extract):
    """Whole-article plain text (`exsectionformat=wiki`) -> the Plot section only.
    Takes everything under the first plot-like heading down to the next heading of
    the same-or-higher level, so plot subsections (e.g. per-season) are kept.
    None if the article has no plot-like section."""
    heads = list(_HEADING.finditer(extract))
    for i, h in enumerate(heads):
        if h.group(2).strip().lower() in PLOT_HEADINGS:
            level = len(h.group(1))
            end = len(extract)
            for nxt in heads[i + 1:]:
                if len(nxt.group(1)) <= level:  # next same/higher heading ends the section
                    end = nxt.start()
                    break
            return extract[h.end():end].strip() or None
    return None


async def fetch_plot(session, wikipedia_url, *, gate, max_retries, timeout):
    """One gate-paced TextExtracts request -> the Plot section text. See module
    docstring for the {'plot', 'error'} contract. `maxlag=5` is MediaWiki
    etiquette: when replica lag is high the API returns a retryable error rather
    than adding load."""
    page = _title_from_url(wikipedia_url)
    try:
        r = await paced_request_async(
            session, ENDPOINT, gate=gate, max_retries=max_retries, timeout=timeout,
            method="GET", headers=HEADERS,
            params={
                "action": "query", "prop": "extracts", "explaintext": "1",
                "exsectionformat": "wiki", "redirects": "1", "maxlag": "5",
                "format": "json", "titles": page,
            },
        )
        if r.status_code != 200:
            return {"plot": None, "error": f"HTTP {r.status_code}"}  # retryable
        data = r.json()
        if "error" in data:  # e.g. maxlag -- retryable
            return {"plot": None, "error": str(data["error"])[:200]}
        pages = (data.get("query") or {}).get("pages") or {}
        page_obj = next(iter(pages.values()), {})
        extract = page_obj.get("extract")
        if not extract:
            return {"plot": None, "error": None}  # no article text -> terminal
        return {"plot": slice_plot(extract), "error": None}
    except Exception as e:
        return {"plot": None, "error": str(e)[:300]}
