import html
import re


def strip_html(text):
    if not text:
        return ""
    text = text.replace("<br/>", "\n").replace("<br>", "\n").replace("<br />", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _first_plot(edges):
    if not edges:
        return None
    return strip_html(edges[0]["node"]["plotText"]["plaidHtml"]) or None


def parse(title):
    """IMDb Title_Storyline title JSON -> enrichment record. No 'error' key --
    the driver adds that on fetch failure. certificate/keywords_total dropped:
    certificate comes from TMDB, and there's no home for keywords_total."""
    return {
        "imdb_id": title.get("id"),
        "outline": _first_plot(title.get("outlines", {}).get("edges", [])),
        "summary": _first_plot(title.get("summaries", {}).get("edges", [])),
        "synopsis": _first_plot(title.get("synopses", {}).get("edges", [])),
        "keywords": [
            k["node"]["text"]
            for k in title.get("storylineKeywords", {}).get("edges", [])
        ],
        "taglines": [
            strip_html(t["node"]["text"])
            for t in title.get("taglines", {}).get("edges", [])
        ],
        "genres": [g["text"] for g in title.get("genres", {}).get("genres", [])],
    }
