import sqlite3
import asyncio
import re
import json
import random
import time
from datetime import datetime, timezone
import curl_cffi.requests as requests
from parsel import Selector
from cinesync.paths import DATA_DIR
from cinesync.ingestion.db_crud import known_tmdb_ids

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONCURRENCY = 8  # start conservative, see optimization notes below
DELAY_RANGE = (0.5, 1.5)  # jitter after every request (success OR failure)
COMMIT_EVERY = 25  # batch commits instead of one per row
PROGRESS_EVERY = 100  # print a progress/ETA line every N completions

FAILURE_LOG_PATH = DATA_DIR / "letterboxd_scrape_failures.jsonl"

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.AsyncSession(impersonate="chrome124")

INSERT_SQL = """
    INSERT OR REPLACE INTO letterboxd_movie_stats (
        title_id, tmdb_id, name, rating_value, rating_count, review_count,

        rating_0_5_count, rating_1_0_count, rating_1_5_count, rating_2_0_count,
        rating_2_5_count, rating_3_0_count, rating_3_5_count, rating_4_0_count,
        rating_4_5_count, rating_5_0_count,

        watches, lists, likes, top_rank
    )
    VALUES (
        ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?
    )
"""


# ---------------------------------------------------------------------------
# Failure logging — appended immediately, not batched, so a mid-run crash
# never loses the record of what failed and why.
# ---------------------------------------------------------------------------
def log_failure(tmdb_id: int, error_type: str, error_msg: str) -> None:
    entry = {
        "tmdb_id": tmdb_id,
        "error_type": error_type,
        "error_message": error_msg[:300],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FAILURE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Fetch + parse a single title
# ---------------------------------------------------------------------------
async def get_letterboxd_data(tmdb_id: int, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            r_main = await session.get(
                f"https://letterboxd.com/tmdb/{tmdb_id}/",
                headers=BASE_HEADERS,
                timeout=15,
            )
            r_main.raise_for_status()

            slug_match = re.search(r"/film/([^/]+)/?", r_main.url)
            if not slug_match:
                raise ValueError(f"Could not extract slug from URL: {r_main.url}")
            slug = slug_match.group(1)
            sel = Selector(text=r_main.text)

            ld_text = sel.css('script[type="application/ld+json"]::text').get()
            if not ld_text:
                raise ValueError("No JSON-LD found on page")

            ld_text = (
                ld_text.replace("/* <![CDATA[ */", "").replace("/* ]]> */", "").strip()
            )
            ld_data = json.loads(ld_text)
            if not ld_data.get("name"):
                raise ValueError("JSON-LD present but missing 'name'")

            agg = ld_data.get("aggregateRating") or {}

            csi_headers = {
                **BASE_HEADERS,
                "Accept": "*/*",
                "Referer": r_main.url,
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
                "tmdb_id": tmdb_id,
                "slug": slug,
                "name": ld_data.get("name"),
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

                result["histogram"].append(
                    {
                        "rating": label,
                        "count": count,
                    }
                )

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
            log_failure(tmdb_id, type(e).__name__, str(e))
            return None
        finally:
            await asyncio.sleep(random.uniform(*DELAY_RANGE))


def build_row(film: dict) -> tuple:
    hist = {h["rating"]: h["count"] for h in film["histogram"]}
    return (
        f"movie_{film['tmdb_id']}",
        film["tmdb_id"],
        film["name"],
        film["ratingValue"],
        film["ratingCount"],
        film["reviewCount"],
        hist.get("half-★", 0),
        hist.get("★", 0),
        hist.get("★½", 0),
        hist.get("★★", 0),
        hist.get("★★½", 0),
        hist.get("★★★", 0),
        hist.get("★★★½", 0),
        hist.get("★★★★", 0),
        hist.get("★★★★½", 0),
        hist.get("★★★★★", 0),
        film["stats"].get("watches"),
        film["stats"].get("lists"),
        film["stats"].get("likes"),
        film["stats"].get("top_rank"),
    )


async def main():
    conn = sqlite3.Connection(DATA_DIR / "cinesync.db")
    all_tmdb_ids = known_tmdb_ids(conn, content_type="movie")
    conn.close()

    # Move to cinesync.ingestion.db_crud
    conn_letterboxd = sqlite3.Connection(DATA_DIR / "letterboxd.db")
    conn_letterboxd.execute("PRAGMA journal_mode=WAL;")

    try:
        already_scraped = {
            row[0]
            for row in conn_letterboxd.execute(
                "SELECT tmdb_id FROM letterboxd_movie_stats"
            )
        }
    except sqlite3.OperationalError:
        already_scraped = set()

    tmdb_ids = [tid for tid in all_tmdb_ids if tid not in already_scraped]
    total = len(tmdb_ids)
    skipped = len(all_tmdb_ids) - total

    print(
        f"{len(all_tmdb_ids)} total candidates, {skipped} already scraped, "
        f"{total} remaining."
    )

    if total == 0:
        print("Nothing to do.")
        conn_letterboxd.close()
        return

    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [get_letterboxd_data(tid, semaphore) for tid in tmdb_ids]

    success_count = 0
    fail_count = 0
    pending = 0
    start = time.monotonic()

    try:
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                conn_letterboxd.execute(INSERT_SQL, build_row(result))
                success_count += 1
                pending += 1
                if pending >= COMMIT_EVERY:
                    conn_letterboxd.commit()
                    pending = 0
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
        conn_letterboxd.commit()
        conn_letterboxd.close()
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
