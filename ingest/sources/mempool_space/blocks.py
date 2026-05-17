import os
from datetime import datetime, timezone

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


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/v1/blocks", timeout=timeout)
    r.raise_for_status()
    blocks = r.json()
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
