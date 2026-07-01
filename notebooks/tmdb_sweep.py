import sqlite3, requests, threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from cinesync.sync_pipeline import (
    known_tmdb_ids,
    fetch_discover_page,
    fetch_title_details,
)
from cinesync.tmdb_parser import parse_tmdb_response
from cinesync.db_writer import upsert_parsed_title
from cinesync.date_windows import resolve_windows_under_cap
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config
from cinesync.utils.net import force_ipv4

force_ipv4()

config = load_config()

tmdb_api_key = config["apis"]["tmdb_api_key"]
conn = sqlite3.Connection(DATA_DIR / "cinesync.db")
lang_filters = config["discover_sweep"]
param_keys = [
    "original_language",
    "min_runtime_minutes",
    "min_vote_count",
    "date_gte",
    "date_lte",
]

MAX_WORKERS = 10


# Multithread Helper Functions
def get_session(thread_local):
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session


def fetch_only(tmdb_id, content_type, lang, thread_local):
    details = fetch_title_details(
        content_type, tmdb_id, tmdb_api_key, get_session(thread_local)
    )
    return tmdb_id, parse_tmdb_response(
        details, content_type=content_type, source=f"discover_lang_{lang}"
    )


def probe(gte, lte, content_type, probe_session, **params):
    payload = fetch_discover_page(
        content_type,
        1,
        tmdb_api_key,
        probe_session,
        date_gte=gte,
        date_lte=lte,
        **params,
    )
    return payload.get("total_pages", 1)


# Main Loop
for filters in lang_filters:
    for content_type in ("tv", "movie"):
        params = {key: filters[i] for i, key in enumerate(param_keys)}
        print(
            f"\nLanguage: {params['original_language']}, Content Type: {content_type}"
        )
        probe_session = requests.Session()

        # --- Pre-windowing probe: the control total (bounded to floor..ceiling) ---
        probe_full = fetch_discover_page(
            content_type, 1, tmdb_api_key, probe_session, **params
        )

        probe_total_results = probe_full.get("total_results", 0)
        probe_total_pages = probe_full.get("total_pages", 0)

        print(
            f"\nPROBE (control): {probe_total_results} titles across {probe_total_pages} pages"
        )

        SWEEP_DATE_GTE = params.pop("date_gte")
        SWEEP_DATE_LTE = params.pop("date_lte")

        known_ids = known_tmdb_ids(conn, content_type)

        thread_local = threading.local()

        # --- Resolve windows over the same range ---
        windows = resolve_windows_under_cap(
            probe, SWEEP_DATE_GTE, SWEEP_DATE_LTE, content_type, probe_session, **params
        )
        print(f"\nResolved {len(windows)} date windows")

        total_discovered = (
            0  # titles the sweep SAW (should reconcile ~ probe_total_results)
        )
        total_fetched = (
            0  # titles actually detail-fetched + written (excludes already_known)
        )
        total_already_known = 0

        for gte, lte in windows:
            w0 = fetch_discover_page(
                content_type,
                1,
                tmdb_api_key,
                probe_session,
                date_gte=gte,
                date_lte=lte,
                **params,
            )
            win_results = w0.get("total_results", 0)
            total_pages = min(w0.get("total_pages", 1), 500)
            total_discovered += win_results
            print(f"\nWindow {gte}..{lte}: {win_results} titles, {total_pages} pages")

            for page in range(1, total_pages + 1):
                payload = fetch_discover_page(
                    content_type,
                    page,
                    tmdb_api_key,
                    probe_session,
                    date_gte=gte,
                    date_lte=lte,
                    **params,
                )
                to_fetch = [
                    e["id"] for e in payload["results"] if e["id"] not in known_ids
                ]
                total_already_known += len(payload["results"]) - len(to_fetch)

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                    futures = {
                        pool.submit(
                            fetch_only,
                            tid,
                            content_type,
                            params["original_language"],
                            thread_local,
                        ): tid
                        for tid in to_fetch
                    }
                    for fut in as_completed(futures):
                        futures.pop(fut)
                        tmdb_id, parsed = fut.result()
                        upsert_parsed_title(conn, parsed)
                        known_ids.add(tmdb_id)
                        total_fetched += 1
                        del fut

        # --- Reconciliation ---
        print("\n=== RECONCILIATION ===")
        print(f"Probe control total:         {probe_total_results}")
        print(f"Sum of window totals (seen): {total_discovered}")
        print(
            f"  -> discovered/probe ratio: {total_discovered / max(probe_total_results, 1):.3f} (expect ~1.0-1.02)"
        )
        print(f"Detail-fetched & written:    {total_fetched}")
        print(f"Skipped (already known):     {total_already_known}")
        print(f"Fetched + known:             {total_fetched + total_already_known}")
