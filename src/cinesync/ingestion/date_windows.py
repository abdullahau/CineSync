from datetime import date

TMDB_MAX_PAGES = 500


def earliest_date(probe_payload: dict, content_type: str) -> str | None:
    date_field = "release_date" if content_type == "movie" else "first_air_date"
    results = probe_payload.get("results", [])
    for row in results:
        value = row.get(date_field)
        if value:
            return value
    return None


def split_window(gte: str, lte: str):
    start = date.fromisoformat(gte)
    end = date.fromisoformat(lte)
    if start >= end:
        return [(gte, lte)]

    mid_ordinal = (start.toordinal() + end.toordinal()) // 2
    mid = date.fromordinal(mid_ordinal)
    next_day = date.fromordinal(mid_ordinal + 1)
    return [(gte, mid.isoformat()), (next_day.isoformat(), lte)]


def resolve_windows(
    probe_window,
    date_gte,
    date_lte,
    content_type,
    probe_session,
    max_iterations=2000,
    **params,
):
    """
    Turn a broad date range into a list of (gte, lte, total_pages,
    total_results) windows that each stay under TMDB_MAX_PAGES.

    Starts from the FULL range as a single window and bisects by date
    only when a window's probed page count is still over the cap.
    Sparse eras resolve in a single probe; dense eras keep splitting
    until they fit. No pre-chunking needed -- the bisection finds the
    right granularity for however density happens to be distributed,
    rather than assuming a fixed chunk size.
    """
    todo = [(date_gte, date_lte)]
    resolved = []
    iterations = 0
    while todo:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError(
                "resolve_windows exceeded max_iterations -- probe_window may be misbehaving"
            )
        gte, lte = todo.pop()
        total_pages, total_results = probe_window(
            gte, lte, content_type, probe_session, **params
        )
        if total_pages <= TMDB_MAX_PAGES:
            resolved.append((gte, lte, total_pages, total_results))
        else:
            halves = split_window(gte, lte)
            if len(halves) == 1:
                resolved.append((gte, lte, total_pages, total_results))
            else:
                todo.extend(halves)
    return sorted(resolved)
