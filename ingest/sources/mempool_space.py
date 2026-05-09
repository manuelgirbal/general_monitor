import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("MEMPOOL_SPACE_BASE", "https://mempool.space/api")
SOURCE_NAME = "mempool_space.mempool"

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "tx_count": pl.Int32,
    "vsize": pl.Int64,
    "total_fee_btc": pl.Float64,
    "fee_p10": pl.Float64,
    "fee_p50": pl.Float64,
    "fee_p90": pl.Float64,
}


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/mempool", timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return pl.DataFrame(
        {
            "ts": [datetime.now(tz=timezone.utc)],
            "tx_count": [int(data["count"])],
            "vsize": [int(data["vsize"])],
            "total_fee_btc": [float(data["total_fee"]) / 1e8],
            "fee_p10": [None],
            "fee_p50": [None],
            "fee_p90": [None],
        },
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO mempool_snapshots
                (ts, tx_count, vsize, total_fee_btc, fee_p10, fee_p50, fee_p90)
            SELECT ts, tx_count, vsize, total_fee_btc, fee_p10, fee_p50, fee_p90
            FROM _df
            ON CONFLICT (ts) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height
