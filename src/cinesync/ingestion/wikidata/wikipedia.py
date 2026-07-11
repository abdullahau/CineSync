"""
Stage B: fetch a title's Plot section from its English Wikipedia article.

Input is the article URL from the Wikidata pass (title_wikidata_meta.
wikipedia_url). Two api.php calls: list sections, find the plot heading, fetch
that section's HTML, strip to text. Returns

    {'plot': <text>|None, 'error': <str>|None}

Semantics match the IMDb enrichment convention used elsewhere:
  - success with a plot -> {'plot': text, 'error': None}
  - article has no plot-like section -> {'plot': None, 'error': None}
    (a legitimate, terminal outcome -- NOT retried; log-and-skip)
  - network/API failure -> {'plot': None, 'error': msg}  (retried next run)

Config lives under the `wikipedia` block; DEFAULTS apply if absent.
"""

from urllib.parse import unquote
import requests
from parsel import Selector
from cinesync.utils.net import paced_request
from cinesync.ingestion.wikidata import USER_AGENT

# Endpoint lives in code; pacing comes from rate_limiting.wikipedia. The UA's
# contact email is imported from EMAIL env via the package USER_AGENT.
ENDPOINT = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": USER_AGENT}

# Plot-section headings vary across articles; check them all (lowercased).
PLOT_HEADINGS = {"plot", "plot summary", "synopsis", "premise", "plot synopsis"}


def new_session():
    return requests.Session()


def _api_get(session, params):
    """GET api.php via the shared paced_request (retry/backoff/pacing from
    rate_limiting.wikipedia). Raises on a persistent non-200 or connection
    failure -- fetch_plot catches and turns it into an {'error': ...}."""
    r = paced_request(
        session, ENDPOINT, service="wikipedia", method="GET",
        params=params, headers=HEADERS,
    )
    r.raise_for_status()
    return r.json()


def _title_from_url(wikipedia_url):
    return unquote(wikipedia_url.rsplit("/", 1)[-1])


def strip_plot_html(html):
    """Wikipedia section HTML -> clean plain text. Drops reference superscripts,
    edit-section links, and <style>, then emits one line per block element
    (paragraph / list item / subsection heading) in document order with inline
    whitespace collapsed. One line per block (vs a naive ::text join) is what
    preserves paragraph boundaries -- text nodes alone carry no newlines."""
    sel = Selector(text=html)
    sel.css("sup.reference, span.mw-editsection, style").remove()
    lines = []
    for block in sel.css("p, li, h2, h3, h4"):
        txt = " ".join("".join(block.css("::text").getall()).split())
        if txt:
            lines.append(txt)
    return "\n".join(lines).strip() or None


def fetch_plot(session, wikipedia_url):
    """Fetch and strip the Plot section for one article URL. See module docstring
    for the {'plot', 'error'} contract."""
    title = _title_from_url(wikipedia_url)
    try:
        secs = _api_get(
            session,
            {"action": "parse", "page": title, "prop": "sections", "format": "json"},
        )
        sections = (secs.get("parse") or {}).get("sections")
        if sections is None:
            return {"plot": None, "error": f"no parse.sections for {title!r}"}
        idx = next(
            (s["index"] for s in sections
             if s.get("line", "").strip().lower() in PLOT_HEADINGS),
            None,
        )
        if idx is None:
            return {"plot": None, "error": None}  # no plot section -- terminal, don't retry

        page = _api_get(
            session,
            {"action": "parse", "page": title, "section": idx,
             "prop": "text", "format": "json"},
        )
        html = ((page.get("parse") or {}).get("text") or {}).get("*")
        if not html:
            return {"plot": None, "error": f"no section text for {title!r} #{idx}"}
        return {"plot": strip_plot_html(html), "error": None}
    except Exception as e:
        return {"plot": None, "error": str(e)[:300]}
