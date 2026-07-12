"""
Wikidata / Wikipedia enrichment driver -- two stages, single-threaded.

Run:  uv run --env-file .env python pipelines/wikidata_ingest.py

Stage A -- Wikidata via QLever (BULK, not per-title WDQS):
    two global scans keyed on imdb_id -- the spine (Wikipedia URL + RT slug) and
    all award statements -- filtered to our titles, labels resolved separately,
    written in one transaction (crud.replace_wikidata_data). It's a full refresh:
    re-running re-fetches (~15s) and full-replaces source='wikidata', so it's
    idempotent rather than incrementally resumable.

Stage B -- Wikipedia plot (per title):
    fetch + strip the Plot section for each title_wikidata_meta.wikipedia_url,
    write title_plots.wikipedia_plot via crud.upsert_wikipedia_plot.
    Resume: crud.titles_missing_wikipedia_plot drops a title once fetched.
"""

import sqlite3
from cinesync.paths import DB_PATH
from cinesync.config_loader import load_config
from cinesync.ingestion import crud
from cinesync.ingestion.wikidata import sparql, wikipedia
from cinesync.ingestion.wikidata import parse as wd_parse


def run_wikidata_stage(conn):
    """Stage A: QLever bulk export -> awards + meta + opportunistic RT slug."""
    targets = crud.wikidata_target_titles(conn)  # (title_id, imdb_id, wikidata_id)
    imdb_to_title = {imdb: tid for tid, imdb, _wd in targets if imdb}
    if not imdb_to_title:
        print("Stage A (Wikidata): no titles with an imdb_id -- nothing to do.")
        return
    session = sparql.new_session()
    print(f"Stage A (Wikidata/QLever): {len(imdb_to_title)} titles with imdb_id.")

    # 1. spine: Wikipedia URL + RT slug, filtered to our titles.
    spine = sparql.fetch_spine(session)
    url_by_title, rt_rows = wd_parse.assemble_spine(spine, imdb_to_title)
    print(f"  spine: {len(spine):,} rows -> {len(url_by_title)} enwiki, {len(rt_rows)} RT slugs")

    # 2. award statements (global scan), filtered to our titles.
    stmts = sparql.fetch_award_statements(session)
    ours = [s for s in stmts if s["imdb_id"] in imdb_to_title]
    print(f"  awards: {len(stmts):,} statements -> {len(ours):,} for our titles")

    # 3. resolve just the labels that actually appear (cheap, batched).
    award_labels = sparql.fetch_labels(session, {s["award_qid"] for s in ours})
    person_labels = sparql.fetch_labels(
        session, {s["person_qid"] for s in ours if s["level"] == "person"})
    award_rows = wd_parse.assemble_awards(ours, award_labels, person_labels, imdb_to_title)

    # 4. stamp wikidata_fetched_at for EVERY attempted title (done-flag), even
    #    those with no spine row and no awards.
    meta_rows = [(tid, url_by_title.get(tid)) for tid in imdb_to_title.values()]

    crud.replace_wikidata_data(conn, meta_rows, rt_rows, award_rows)
    print(f"Stage A complete: {len(meta_rows)} meta, {len(rt_rows)} RT, "
          f"{len(award_rows):,} award rows written.")


def run_wikipedia_stage(conn):
    """Stage B: Wikipedia plot text per resolved article URL."""
    work = crud.titles_missing_wikipedia_plot(conn)
    if not work:
        print("Stage B (Wikipedia): nothing to do.")
        return
    session = wikipedia.new_session()
    print(f"Stage B (Wikipedia): {len(work)} titles")

    got = empty = errored = 0
    for i, (title_id, wikipedia_url) in enumerate(work, 1):
        res = wikipedia.fetch_plot(session, wikipedia_url)
        crud.upsert_wikipedia_plot(conn, title_id, res["plot"], res["error"])
        if res["error"] is not None:
            errored += 1
        elif res["plot"]:
            got += 1
        else:
            empty += 1
        if i % 25 == 0:
            print(f"  ...{i}/{len(work)}  (plots={got}, no-section={empty}, errors={errored})")

    print(f"Stage B complete: {got} plots, {empty} no-section, {errored} errored.")


def main():
    load_config()  # fail fast on a missing/broken config before any network work
    conn = sqlite3.connect(DB_PATH)
    try:
        run_wikidata_stage(conn)
        run_wikipedia_stage(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
