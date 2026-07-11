import sqlite3
import asyncio
import re
import json
import random
import time
from datetime import datetime, timezone
import curl_cffi.requests as requests
from parsel import Selector
from cinesync.paths import DB_PATH, LOGS_DIR
from cinesync.ingestion import crud


CONCURRENCY = 8
DELAY_RANGE = (0.5, 1.5)  # jitter after every request (success OR failure)
PROGRESS_EVERY = 100  # print a progress/ETA line every N completions

FAILURE_LOG_PATH = LOGS_DIR / "letterboxd_scrape_failures.jsonl"

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.AsyncSession(impersonate="chrome124")


def log_failure(
    title_id: str,
    imdb_id: str | None,
    tmdb_id: int,
    error_type: str,
    error_msg: str,
) -> None:
    entry = {
        "title_id": title_id,
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "error_type": error_type,
        "error_message": error_msg[:300],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FAILURE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# Resolve a Letterboxd film page, trying the IMDb slug first (it resolves TV /
# limited series too) and falling back to the TMDB slug. Any failure on the
# first route — HTTP error, unresolvable slug, or missing/invalid JSON-LD —
# triggers the fallback.
#
# The /tmdb/ fallback is MOVIE-ONLY. Letterboxd's /tmdb/{id}/ route only knows
# movies, and TMDB movie/TV IDs share one numeric namespace — so /tmdb/{id}/ for
# a TV id would resolve to the *movie* with that id and attach the wrong film's
# stats. For TV, imdb is therefore the only safe route; a TV title without an
# imdb_id has no route and fails fast (logged, expected gap — not a bug).
async def resolve_film_page(imdb_id: str | None, tmdb_id: int, content_type: str):
    routes = []
    if imdb_id:
        routes.append(("imdb", f"https://letterboxd.com/imdb/{imdb_id}/"))
    if content_type != "tv":
        routes.append(("tmdb", f"https://letterboxd.com/tmdb/{tmdb_id}/"))

    if not routes:
        raise ValueError("No resolvable route: TV title without an imdb_id")

    last_error = None
    for i, (route, url) in enumerate(routes):
        try:
            r = await session.get(url, headers=BASE_HEADERS, timeout=15)
            r.raise_for_status()

            slug_match = re.search(r"/film/([^/]+)/?", r.url)
            if not slug_match:
                raise ValueError(f"Could not extract slug from URL: {r.url}")
            slug = slug_match.group(1)

            sel = Selector(text=r.text)
            ld_text = sel.css('script[type="application/ld+json"]::text').get()
            if not ld_text:
                raise ValueError("No JSON-LD found on page")

            ld_text = (
                ld_text.replace("/* <![CDATA[ */", "").replace("/* ]]> */", "").strip()
            )
            ld_data = json.loads(ld_text)
            if not ld_data.get("name"):
                raise ValueError("JSON-LD present but missing 'name'")

            return slug, ld_data, r.url, route
        except Exception as e:
            last_error = e
            # Pace the fallback request like any other (only if one remains).
            if i < len(routes) - 1:
                await asyncio.sleep(random.uniform(*DELAY_RANGE))

    raise last_error or ValueError("No Letterboxd film page resolved")


# Fetch + parse a single title. Resolution is keyed by IMDb ID (so TV/limited
# series resolve), with a TMDB-ID fallback for titles that lack an imdb_id or
# whose IMDb slug fails to resolve.
async def get_letterboxd_data(
    title_id: str,
    imdb_id: str | None,
    tmdb_id: int,
    content_type: str,
    semaphore: asyncio.Semaphore,
):
    async with semaphore:
        try:
            slug, ld_data, resolved_url, resolved_via = await resolve_film_page(
                imdb_id, tmdb_id, content_type
            )

            agg = ld_data.get("aggregateRating") or {}

            csi_headers = {
                **BASE_HEADERS,
                "Accept": "*/*",
                "Referer": resolved_url,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }

            hist_task = session.get(
                f"https://letterboxd.com/csi/film/{slug}/rating-histogram/",
                headers=csi_headers,
                timeout=15,
            )
            stats_task = session.get(
                f"https://letterboxd.com/csi/film/{slug}/stats/",
                headers=csi_headers,
                timeout=15,
            )
            r_hist, r_stats = await asyncio.gather(hist_task, stats_task)

            if r_hist.status_code != 200:
                raise RuntimeError(
                    f"Histogram fetch failed: status {r_hist.status_code}"
                )

            result = {
                "title_id": title_id,
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
                "slug": slug,
                "resolved_via": resolved_via,
                "year": ld_data.get("dateCreated", "")[:4],
                "ratingValue": agg.get("ratingValue"),
                "ratingCount": agg.get("ratingCount"),
                "reviewCount": agg.get("reviewCount"),
                "histogram": [],
                "stats": {},
            }

            sel_hist = Selector(text=r_hist.text)
            for col in sel_hist.css("tr.column"):
                label = col.css("th._sr-only::text").get(default="").strip()
                title_attr = col.css("a.barcolumn::attr(title)").get(default="")

                count_match = re.search(r"([\d,]+)", title_attr)
                count = int(count_match.group(1).replace(",", "")) if count_match else 0

                result["histogram"].append({"rating": label, "count": count})

            if r_stats.status_code == 200:
                sel_stats = Selector(text=r_stats.text)

                def parse_aria_label(text):
                    if not text:
                        return None
                    text = text.replace("&nbsp;", " ")
                    m = re.search(r"([\d,]+)", text)
                    return int(m.group(1).replace(",", "")) if m else None

                result["stats"] = {
                    "watches": parse_aria_label(
                        sel_stats.css("div.-watches::attr(aria-label)").get()
                    ),
                    "lists": parse_aria_label(
                        sel_stats.css("div.-lists::attr(aria-label)").get()
                    ),
                    "likes": parse_aria_label(
                        sel_stats.css("div.-likes::attr(aria-label)").get()
                    ),
                    "top_rank": parse_aria_label(
                        sel_stats.css("div.-topFilms::attr(aria-label)").get()
                    ),
                }

            return result

        except Exception as e:
            log_failure(title_id, imdb_id, tmdb_id, type(e).__name__, str(e))
            return None
        finally:
            await asyncio.sleep(random.uniform(*DELAY_RANGE))


async def main():
    conn = sqlite3.connect(DB_PATH)

    # Titles with no Letterboxd stats row yet — the anti-join is the resume
    # mechanism. No imdb_id filter: titles without one fall back to the TMDB
    # slug (movies only), so they're still worth attempting.
    to_scrape = crud.titles_missing_letterboxd_stats(conn)

    total = len(to_scrape)
    no_imdb = sum(1 for _, imdb, _, _ in to_scrape if not imdb)
    movie_no_imdb = sum(1 for _, imdb, _, ct in to_scrape if not imdb and ct != "tv")
    tv_no_imdb = sum(1 for _, imdb, _, ct in to_scrape if not imdb and ct == "tv")
    print(
        f"{total} titles missing Letterboxd stats. {no_imdb} have no imdb_id: "
        f"{movie_no_imdb} are movies (will try the tmdb fallback) and "
        f"{tv_no_imdb} are TV (no resolvable route — tmdb is movie-only and IDs "
        f"collide across types — these fail without a network call)."
    )

    if total == 0:
        print("Nothing to do.")
        conn.close()
        return

    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        get_letterboxd_data(tid, imdb, tmdb, ct, semaphore)
        for tid, imdb, tmdb, ct in to_scrape
    ]

    success_count = 0
    fail_count = 0
    start = time.monotonic()

    try:
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                crud.upsert_letterboxd_stats(conn, result)
                success_count += 1
            else:
                fail_count += 1

            done = success_count + fail_count
            if done % PROGRESS_EVERY == 0:
                elapsed = time.monotonic() - start
                rate = done / elapsed if elapsed else 0
                eta_min = (total - done) / rate / 60 if rate else float("inf")
                print(
                    f"[{done}/{total}] ok={success_count} fail={fail_count} "
                    f"rate={rate:.2f}/s eta={eta_min:.1f}min"
                )
    finally:
        conn.close()
        await session.close()

    elapsed = time.monotonic() - start
    print(
        f"\nFinished in {elapsed / 60:.1f}min. "
        f"{success_count} succeeded, {fail_count} failed out of {total}."
    )
    if fail_count:
        print(f"Failure details: {FAILURE_LOG_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
