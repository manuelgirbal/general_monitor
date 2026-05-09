import os
import sys
import time
from datetime import datetime, timezone

import httpx

from db import get_conn, init_schema
from ingest.sources import mempool_space

SOURCES = (mempool_space,)


def _log_run(conn, ts, source, status, latency_ms, error=None):
    conn.execute(
        """
        INSERT INTO ingest_runs (ts, source, status, latency_ms, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (ts, source) DO NOTHING
        """,
        [ts, source, status, latency_ms, error],
    )


def run_once() -> int:
    init_schema()
    conn = get_conn(readonly=False)
    user_agent = os.environ.get("INGEST_USER_AGENT", "general_monitor/0.1")
    client = httpx.Client(headers={"User-Agent": user_agent})
    failures = 0
    try:
        for source in SOURCES:
            ts = datetime.now(tz=timezone.utc)
            t0 = time.monotonic()
            try:
                df = source.fetch(client)
                source.upsert(conn, df)
                latency = int((time.monotonic() - t0) * 1000)
                _log_run(conn, ts, source.SOURCE_NAME, "ok", latency)
                print(f"[{ts.isoformat()}] ok  {source.SOURCE_NAME} {latency}ms")
            except Exception as e:
                latency = int((time.monotonic() - t0) * 1000)
                err = f"{type(e).__name__}: {e}"
                _log_run(conn, ts, source.SOURCE_NAME, "error", latency, err)
                print(
                    f"[{ts.isoformat()}] err {source.SOURCE_NAME} {latency}ms {err}",
                    file=sys.stderr,
                )
                failures += 1
    finally:
        client.close()
        conn.close()
    return failures


if __name__ == "__main__":
    run_once()
