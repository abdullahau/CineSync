"""
Phase 1b helper: split a discover sweep's date range into windows that
each stay under TMDB's hard 500-page pagination cap.

TMDB refuses any page > 500 (status_code 22). A broad sweep (e.g. all
English movies since 1940) can be ~2000 pages, so it must be broken
into date-bracketed sub-queries via primary_release_date.gte/.lte
(movies) or first_air_date.gte/.lte (TV).

Title density is NOT uniform over time -- the streaming era produces
far more titles per year than the 1940s -- so a FIXED window size
(e.g. 10 years) doesn't reliably stay under 500 pages: a dense modern
window can blow the cap and silently truncate. The adaptive approach
here probes each window's page count and splits any window still over
the cap in half, recursively, so no data is ever silently lost
regardless of how titles cluster in time.
"""

from datetime import date

DATE_PARAM = {"movie": "primary_release_date", "tv": "first_air_date"}
TMDB_MAX_PAGES = 500


def date_param_names(content_type: str):
    """Returns (gte_param, lte_param) for the given content type."""
    base = DATE_PARAM.get(content_type)
    if base is None:
        raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")
    return f"{base}.gte", f"{base}.lte"


def initial_windows(floor_year: int, ceiling_year: int, chunk_years: int = 10):
    """
    Split [floor_year, ceiling_year] into coarse windows as a starting
    point. These are just the FIRST guess -- adaptive splitting (in the
    notebook loop, using probe_total_pages) narrows any that are still
    too dense. Each window is an inclusive (start_date, end_date) pair
    of 'YYYY-MM-DD' strings.
    """
    windows = []
    start = floor_year
    while start <= ceiling_year:
        end = min(start + chunk_years - 1, ceiling_year)
        windows.append((f"{start}-01-01", f"{end}-12-31"))
        start = end + 1
    return windows


def split_window(gte: str, lte: str):
    """
    Split one (gte, lte) window into two roughly-equal halves by date.
    Used when a window's probed page count still exceeds the cap.
    Returns [(gte, mid), (mid+1day, lte)] or, if the window is already
    a single day (can't split further), the original window unchanged
    inside a one-element list (a genuinely single-day window with >500
    pages is not realistically possible on TMDB, but we degrade
    gracefully rather than loop forever).
    """
    start = date.fromisoformat(gte)
    end = date.fromisoformat(lte)
    if start >= end:
        return [(gte, lte)]

    # Midpoint by ordinal day -- robust across leap years / month lengths.
    mid_ordinal = (start.toordinal() + end.toordinal()) // 2
    mid = date.fromordinal(mid_ordinal)
    next_day = date.fromordinal(mid_ordinal + 1)
    return [(gte, mid.isoformat()), (next_day.isoformat(), lte)]


def resolve_windows_under_cap(
    probe_total_pages, date_gte, date_lte, chunk_years=10, max_iterations=2000
):
    """
    Turn a broad date range into a list of (gte, lte) windows that each
    return <= TMDB_MAX_PAGES pages, splitting dense windows adaptively.

    date_gte / date_lte are the full sweep bounds as 'YYYY-MM-DD'
    strings (e.g. config.yaml's discover_filter.date_gte/.date_lte).
    Windowing is done at year granularity for the initial split, so
    only the year portion of these bounds drives initial_windows -- but
    they're accepted as full date strings to match how the rest of the
    pipeline passes dates around.

    probe_total_pages(gte, lte) -> int is a caller-supplied function
    that returns the total_pages TMDB reports for a window's first page
    (in the notebook: fetch page 1 with that window and read
    payload['total_pages']). Kept as an injected callable so this
    function has zero network/API dependency and stays unit-testable.

    Returns the resolved windows sorted chronologically. A window that
    can't be split further (single day) is accepted as-is even if it
    somehow still exceeds the cap -- not realistically reachable, but
    prevents an infinite loop.
    """
    floor_year = int(date_gte[:4])
    ceiling_year = int(date_lte[:4])
    todo = initial_windows(floor_year, ceiling_year, chunk_years)
    resolved = []
    iterations = 0
    while todo:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError(
                "resolve_windows_under_cap exceeded max_iterations -- probe_total_pages may be misbehaving"
            )
        gte, lte = todo.pop()
        if probe_total_pages(gte, lte) <= TMDB_MAX_PAGES:
            resolved.append((gte, lte))
        else:
            halves = split_window(gte, lte)
            if len(halves) == 1:
                resolved.append((gte, lte))
            else:
                todo.extend(halves)
    return sorted(resolved)
