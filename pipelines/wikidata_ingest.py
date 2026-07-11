"""
Wikidata / Wikipedia enrichment driver -- two stages, single-threaded on the
main thread (WDQS and Wikipedia both dislike concurrency, and the DB is
single-writer).

Run:  uv run --env-file .env python pipelines/wikidata_ingest.py

Stage A -- Wikidata SPARQL (batched over Q-ids):
    per batch, fetch award statements + (Wikipedia URL, RT slug), then write
    title_awards / title_wikidata_meta / title_rt via crud.upsert_wikidata_result.
    Resume: crud.titles_missing_wikidata drops a title once its pass lands clean.

Stage B -- Wikipedia plot (per title):
    fetch + strip the Plot section for each title_wikidata_meta.wikipedia_url,
    write title_plots.wikipedia_plot via crud.upsert_wikipedia_plot.
    Resume: crud.titles_missing_wikipedia_plot drops a title once fetched.

Both stages are re-runnable; a crash mid-run just resumes where it left off.
"""

import sqlite3
from cinesync.paths import DB_PATH
from cinesync.config_loader import load_config
from cinesync.ingestion import crud
from cinesync.ingestion.wikidata import sparql, wikipedia
from cinesync.ingestion.wikidata import parse as wd_parse


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def run_wikidata_stage(conn):
    """Stage A: Wikidata SPARQL -> awards + meta + opportunistic RT slug."""
    work = crud.titles_missing_wikidata(conn)
    if not work:
        print("Stage A (Wikidata): nothing to do.")
        return
    batch_size = sparql._cfg()["batch_size"]
    session = sparql.new_session()
    print(f"Stage A (Wikidata): {len(work)} titles, batch_size={batch_size}")

    done = errored = 0
    for batch in _chunks(work, batch_size):
        by_qid = {wikidata_id: title_id for title_id, wikidata_id in batch}
        qids = list(by_qid)

        aw = sparql.fetch_awards(session, qids)
        ln = sparql.fetch_links(session, qids)

        if "error" in aw or "error" in ln:
            msg = f"awards: {aw.get('error')}; links: {ln.get('error')}"
            for title_id in by_qid.values():
                crud.upsert_wikidata_result(conn, title_id, {"error": msg})
            errored += len(by_qid)
            print(f"  batch of {len(qids)} errored -> {msg[:120]}")
            continue

        awards = wd_parse.parse_awards(aw["bindings"])
        links = wd_parse.parse_links(ln["bindings"])
        for qid, title_id in by_qid.items():
            link = links.get(qid, {})
            crud.upsert_wikidata_result(
                conn,
                title_id,
                {
                    "awards": awards.get(qid, []),
                    "wikipedia_url": link.get("wikipedia_url"),
                    "rt_slug": link.get("rt_slug"),
                },
            )
            done += 1
        print(f"  ...{done} done, {errored} errored")

    print(f"Stage A complete: {done} written, {errored} errored (retryable next run).")


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
