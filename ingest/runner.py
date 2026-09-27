import os
import sys
import time
from datetime import datetime, timezone

import httpx

from db import get_conn, init_schema
from ingest.sources import (
    argentinadatos,
    bcra,
    blockchain_info,
    coingecko,
    datos_gob_ar,
    defillama,
    dolarapi,
    yahoo_finance,
)
from ingest.sources.cammesa import demand as cammesa_demand
from ingest.sources.cammesa import generation as cammesa_generation
from ingest.sources.mempool_space import blocks, mempool

# Reachable-node tracking is parked: bitnodes.io was discontinued and the
# replacement is to run our own Bitcoin Core node and query it via RPC.
SOURCES = (
    mempool,
    blocks,
    coingecko,
    blockchain_info,
    dolarapi,
    argentinadatos,
    defillama,
    bcra,
    datos_gob_ar,
    yahoo_finance,
    cammesa_generation,
)

# The generation endpoint only returns the current AR day and can't backfill, so any
# missed day is lost for good. It is polled every INTERVAL_SECONDS in the default loop,
# and monitor-cammesa.timer also forces a run near AR midnight to capture the day's tail.
CAMMESA_SOURCES = (
    cammesa_generation,
    cammesa_demand,
)

GROUPS = {"default": SOURCES, "cammesa": CAMMESA_SOURCES}


def _log_run(conn, ts, source, status, latency_ms, error=None):
    conn.execute(
        """
        INSERT INTO ingest_runs (ts, source, status, latency_ms, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (ts, source) DO NOTHING
        """,
        [ts, source, status, latency_ms, error],
    )


def _last_run_ts(conn):
    rows = conn.execute("SELECT source, max(ts) FROM ingest_runs GROUP BY 1").fetchall()
    return dict(rows)


def _due(sources, force: bool) -> list:
    conn = get_conn(readonly=False)
    try:
        last_runs = _last_run_ts(conn)
    finally:
        conn.close()
    due = []
    now = datetime.now(tz=timezone.utc)
    for source in sources:
        last = last_runs.get(source.SOURCE_NAME)
        if last is not None and not force:
            elapsed = (now - last).total_seconds()
            if elapsed < source.INTERVAL_SECONDS:
                wait = int(source.INTERVAL_SECONDS - elapsed)
                print(f"[{now.isoformat()}] skip {source.SOURCE_NAME} (next in {wait}s)")
                continue
        due.append(source)
    return due


def run_once(sources=SOURCES, force: bool = False) -> int:
    # DuckDB allows a single writer across processes and the app's read-only opens
    # fail while it's held, so all HTTP happens first and the write connection is
    # only open for the inserts.
    init_schema()
    due = _due(sources, force)
    if not due:
        return 0
    user_agent = os.environ.get("INGEST_USER_AGENT", "general_monitor/0.1")
    results = []
    with httpx.Client(headers={"User-Agent": user_agent}) as client:
        for source in due:
            now = datetime.now(tz=timezone.utc)
            t0 = time.monotonic()
            try:
                df, err = source.fetch(client), None
            except Exception as e:
                df, err = None, f"{type(e).__name__}: {e}"
            results.append((source, now, df, err, int((time.monotonic() - t0) * 1000)))

    failures = 0
    conn = get_conn(readonly=False)
    try:
        for source, now, df, err, latency in results:
            if err is None:
                try:
                    source.upsert(conn, df)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
            if err is None:
                _log_run(conn, now, source.SOURCE_NAME, "ok", latency)
                print(f"[{now.isoformat()}] ok   {source.SOURCE_NAME} {latency}ms")
            else:
                _log_run(conn, now, source.SOURCE_NAME, "error", latency, err)
                print(
                    f"[{now.isoformat()}] err  {source.SOURCE_NAME} {latency}ms {err}",
                    file=sys.stderr,
                )
                failures += 1
    finally:
        conn.close()
    return failures


if __name__ == "__main__":
    group = sys.argv[1] if len(sys.argv) > 1 else "default"
    run_once(GROUPS.get(group, SOURCES), force=group == "cammesa")
