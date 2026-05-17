import os
import sys
import time
from datetime import datetime, timezone

import httpx

from db import get_conn, init_schema
from ingest.sources.mempool_space import blocks, mempool

SOURCES = (mempool, blocks)


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


def run_once() -> int:
    init_schema()
    conn = get_conn(readonly=False)
    user_agent = os.environ.get("INGEST_USER_AGENT", "general_monitor/0.1")
    client = httpx.Client(headers={"User-Agent": user_agent})
    failures = 0
    try:
        for source in SOURCES:
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
    run_once()
