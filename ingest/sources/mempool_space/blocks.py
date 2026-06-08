import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("MEMPOOL_SPACE_BASE", "https://mempool.space/api")
SOURCE_NAME = "mempool_space.blocks"
INTERVAL_SECONDS = 120

SCHEMA = {
    "height": pl.Int32,
    "hash": pl.Utf8,
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "tx_count": pl.Int32,
    "size": pl.Int64,
    "weight": pl.Int64,
}


def _to_df(blocks: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "height": [int(b["height"]) for b in blocks],
            "hash": [str(b["id"]) for b in blocks],
            "ts": [
                datetime.fromtimestamp(int(b["timestamp"]), tz=timezone.utc)
                for b in blocks
            ],
            "tx_count": [int(b["tx_count"]) for b in blocks],
            "size": [int(b["size"]) for b in blocks],
            "weight": [int(b["weight"]) for b in blocks],
        },
        schema=SCHEMA,
    )


def _get_json(client: httpx.Client, url: str, timeout: float, retries: int = 4, backoff: float = 2.0):
    for attempt in range(retries):
        try:
            r = client.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (attempt + 1))


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/v1/blocks", timeout=timeout)
    r.raise_for_status()
    return _to_df(r.json())


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO blocks
                (height, hash, ts, tx_count, size, weight)
            SELECT height, hash, ts, tx_count, size, weight
            FROM _df
            ON CONFLICT (height) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(
    client: httpx.Client,
    conn,
    hours: int = 720,
    sleep_s: float = 1.5,
    max_pages: int = 500,
) -> int:
    # mempool.space /v1/blocks returns 15 blocks per page (no API key); paginate by passing
    # the height of the earliest block on the previous page minus 1.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    earliest_height: int | None = None
    inserted = 0
    for _ in range(max_pages):
        url = (
            f"{BASE_URL}/v1/blocks"
            if earliest_height is None
            else f"{BASE_URL}/v1/blocks/{earliest_height - 1}"
        )
        blocks = _get_json(client, url, timeout)
        if not blocks:
            break
        df = _to_df(blocks)
        inserted += upsert(conn, df)
        earliest_height = min(int(b["height"]) for b in blocks)
        min_ts = min(
            datetime.fromtimestamp(int(b["timestamp"]), tz=timezone.utc) for b in blocks
        )
        if min_ts < cutoff:
            break
        time.sleep(sleep_s)
    return inserted
