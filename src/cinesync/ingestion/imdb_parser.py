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


def parse_ratings_histogram(title):
    """IMDb title JSON (ratingsSummary + aggregateRatingsBreakdown) -> rating
    distribution record. No 'error' key -- the driver adds that on fetch
    failure. `votes` is a {1..10: voteCount} dict (None for any absent bucket);
    `total_votes` is ratingsSummary.voteCount, which equals the bucket sum;
    `aggregate_rating` is the 0-10 mean, kept only for a cross-check against
    title_scores.imdb_rating. A title with no ratings yields empty votes and a
    None/0 total."""
    buckets = (
        (title.get("aggregateRatingsBreakdown") or {})
        .get("histogram", {})
        .get("histogramValues", [])
    )
    votes = {b["rating"]: b["voteCount"] for b in buckets}
    summary = title.get("ratingsSummary") or {}
    return {
        "imdb_id": title.get("id"),
        "votes": {i: votes.get(i) for i in range(1, 11)},
        "total_votes": summary.get("voteCount"),
        "aggregate_rating": summary.get("aggregateRating"),
    }
