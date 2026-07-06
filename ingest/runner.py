import os
import sys
import time
from datetime import datetime, timezone

import httpx

from db import get_conn, init_schema
from ingest.sources import argentinadatos, blockchain_info, coingecko, defillama, dolarapi
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
)

# CAMMESA runs on its own daily timer (monitor-cammesa.timer) near end of the AR day,
# not in the every-minute loop: the generation endpoint only returns the current day up
# to now and can't backfill, so one late fetch captures the near-complete curve.
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


def _last_run_ts(conn, source_name):
    row = conn.execute(
        "SELECT max(ts) FROM ingest_runs WHERE source = ?",
        [source_name],
    ).fetchone()
    return row[0] if row else None


def run_once(sources=SOURCES) -> int:
    init_schema()
    conn = get_conn(readonly=False)
    user_agent = os.environ.get("INGEST_USER_AGENT", "general_monitor/0.1")
    client = httpx.Client(headers={"User-Agent": user_agent})
    failures = 0
    try:
        for source in sources:
            now = datetime.now(tz=timezone.utc)
            last = _last_run_ts(conn, source.SOURCE_NAME)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < source.INTERVAL_SECONDS:
                    wait = int(source.INTERVAL_SECONDS - elapsed)
                    print(
                        f"[{now.isoformat()}] skip {source.SOURCE_NAME} "
                        f"(next in {wait}s)"
                    )
                    continue
            t0 = time.monotonic()
            try:
                df = source.fetch(client)
                source.upsert(conn, df)
                latency = int((time.monotonic() - t0) * 1000)
                _log_run(conn, now, source.SOURCE_NAME, "ok", latency)
                print(f"[{now.isoformat()}] ok   {source.SOURCE_NAME} {latency}ms")
            except Exception as e:
                latency = int((time.monotonic() - t0) * 1000)
                err = f"{type(e).__name__}: {e}"
                _log_run(conn, now, source.SOURCE_NAME, "error", latency, err)
                print(
                    f"[{now.isoformat()}] err  {source.SOURCE_NAME} {latency}ms {err}",
                    file=sys.stderr,
                )
                failures += 1
    finally:
        client.close()
        conn.close()
    return failures


if __name__ == "__main__":
    group = sys.argv[1] if len(sys.argv) > 1 else "default"
    run_once(GROUPS.get(group, SOURCES))
