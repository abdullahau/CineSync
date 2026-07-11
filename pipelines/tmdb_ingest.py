import csv, sqlite3, requests, threading, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

from cinesync.ingestion.tmdb import fetch, parse, date_windows
from cinesync.ingestion import crud
from cinesync.paths import DB_PATH, DATA_DIR
from cinesync.config_loader import load_config
from cinesync.utils.net import force_ipv4

force_ipv4()
config = load_config()
tmdb_api_key = config["apis"]["tmdb_api_key"]
conn = sqlite3.Connection(DB_PATH)

MAX_WORKERS = 10
CEILING = f"{date.today().year}-12-31"


def load_ignored_ids(content_type):
    IGNORE_CSV = DATA_DIR / "tmdb_ignore.csv"
    if not IGNORE_CSV.exists():
        return set()
    with open(IGNORE_CSV, newline="", encoding="utf-8") as f:
        return {
            int(row["tmdb_id"])
            for row in csv.DictReader(f)
            if row["content_type"] == content_type
        }


def get_session(thread_local):
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session


def fetch_only(tmdb_id, content_type, source, thread_local):
    """Runs in a worker thread: network + parse only, no DB access."""
    details = fetch.fetch_title_details(
        content_type, tmdb_id, tmdb_api_key, get_session(thread_local)
    )
    return tmdb_id, parse.parse_tmdb_response(
        details, content_type=content_type, source=source
    )


def probe_window(gte, lte, content_type, session, **params):
    """fetch page 1 of a candidate window and report (total_pages, total_results)"""
    payload = fetch.fetch_discover_page(
        content_type, 1, tmdb_api_key, session, date_gte=gte, date_lte=lte, **params
    )
    return payload.get("total_pages", 1), payload.get("total_results", 0)


def run_sweep(content_type, params, source_label, date_gte=None):
    """
    One sweep over one content_type with a discover filter dict whose
    keys already match build_discover_params' kwargs (lang, min_rating,
    min_vote_count, ...). date_gte is derived from a floor probe when
    not supplied (votes/rating); pass it explicitly for a per-language
    floor (lang). Ceiling is always CEILING.
    """
    print(f"\n=== {source_label} | {content_type.upper()} ===")
    probe_session = requests.Session()
    known_ids = crud.known_tmdb_ids(conn, content_type)
    ignored_ids = load_ignored_ids(content_type)
    thread_local = threading.local()

    if date_gte is None:
        floor_probe = fetch.fetch_discover_page(
            content_type, 1, tmdb_api_key, probe_session, date_lte=CEILING, **params
        )
        date_gte = date_windows.earliest_date(floor_probe, content_type) or "1900-01-01"
    print(f"Range: {date_gte} to {CEILING}")

    control = fetch.fetch_discover_page(
        content_type,
        1,
        tmdb_api_key,
        probe_session,
        date_gte=date_gte,
        date_lte=CEILING,
        **params,
    )
    probe_total_results = control.get("total_results", 0)
    print(f"Control total: {probe_total_results} ({control.get('total_pages')} pages)")

    windows = date_windows.resolve_windows(
        probe_window, date_gte, CEILING, content_type, probe_session, **params
    )
    print(f"Resolved {len(windows)} window(s)")

    total_discovered = total_fetched = total_already_known = total_ignored = 0
    capped = []

    for gte, lte, reported, win_results in windows:
        if reported >= 500:
            capped.append((gte, lte, reported))
        pages = min(reported, 500)
        total_discovered += win_results
        print(f"  window {gte}..{lte}: {win_results} titles, {pages} pages")
        window_start = time.monotonic()

        for page in range(1, pages + 1):
            payload = fetch.fetch_discover_page(
                content_type,
                page,
                tmdb_api_key,
                probe_session,
                date_gte=gte,
                date_lte=lte,
                **params,
            )
            results = payload["results"]
            to_fetch = [
                e["id"]
                for e in results
                if e["id"] not in known_ids and e["id"] not in ignored_ids
            ]
            page_ignored = sum(1 for e in results if e["id"] in ignored_ids)
            total_ignored += page_ignored
            total_already_known += len(results) - len(to_fetch) - page_ignored
            print(f"    page {page}/{pages}: {len(to_fetch)} new titles to fetch...")

            page_fetched = page_failed = 0
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {
                    pool.submit(
                        fetch_only, tid, content_type, source_label, thread_local
                    ): tid
                    for tid in to_fetch
                }
                for fut in as_completed(futures):
                    tmdb_id = futures.pop(fut)
                    try:
                        tmdb_id, parsed = fut.result()
                    except Exception as exc:
                        page_failed += 1
                        print(
                            f"    ! failed tmdb_id={tmdb_id}: {type(exc).__name__}: {exc}"
                        )
                        continue
                    crud.upsert_tmdb_title(conn, parsed)
                    known_ids.add(tmdb_id)
                    total_fetched += 1
                    page_fetched += 1

            elapsed = time.monotonic() - window_start
            rate = total_fetched / elapsed if elapsed > 0 else 0
            print(
                f"    page {page}/{pages} done: {page_fetched} fetched, {page_failed} failed  "
                f"|  {elapsed:.0f}s elapsed this window, {rate:.1f} titles/s"
            )

    print(f"--- reconciliation ({source_label}/{content_type}) ---")
    print(
        f"control {probe_total_results}  windows_sum {total_discovered}  "
        f"ratio {total_discovered / max(probe_total_results, 1):.3f}"
    )
    print(
        f"fetched {total_fetched}  already_known {total_already_known}  "
        f"ignored {total_ignored}"
    )
    if capped:
        print(f"\u26a0 {len(capped)} window(s) hit the 500-page cap:")
        for g, l, p in capped:
            print(f"    {g}..{l}: reported {p} pages")


# ============================= driver =============================
sweeps = config["tmdb_discover"]

jobs = []  # (content_type, params, source_label, date_gte)

for content_type in ("movie", "tv"):
    jobs.append((content_type, dict(sweeps["votes"]), "discover_votes", None))

for content_type in ("movie", "tv"):
    r = sweeps["rating"]
    params = {"min_rating": r["min_rating"], "min_vote_count": r["min_vote_count"]}
    jobs.append((content_type, params, "discover_rating", None))

for lang_cfg in sweeps["lang"]:
    lang = lang_cfg["lang"]
    for content_type in ("movie", "tv"):
        params = {"lang": lang, "min_vote_count": lang_cfg["min_vote_count"]}
        jobs.append(
            (content_type, params, f"discover_lang_{lang}", lang_cfg["min_release"])
        )

for content_type, params, source_label, date_gte in jobs:
    try:
        run_sweep(content_type, params, source_label, date_gte=date_gte)
    except Exception as exc:
        print(
            f"\n!!! {source_label}/{content_type} FAILED: {type(exc).__name__}: {exc}"
        )
        print("!!! continuing to next sweep\n")
