import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("MEMPOOL_SPACE_BASE", "https://mempool.space/api")
SOURCE_NAME = "mempool_space.mempool"
INTERVAL_SECONDS = 60

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

    r2 = client.get(f"{BASE_URL}/v1/fees/mempool-blocks", timeout=timeout)
    r2.raise_for_status()
    # feeRange: [min, p10, p25, p50, p75, p90, max] for the next projected block
    fee_range = r2.json()[0]["feeRange"]

    return pl.DataFrame(
        {
            "ts": [datetime.now(tz=timezone.utc)],
            "tx_count": [int(data["count"])],
            "vsize": [int(data["vsize"])],
            "total_fee_btc": [float(data["total_fee"]) / 1e8],
            "fee_p10": [float(fee_range[1])],
            "fee_p50": [float(fee_range[3])],
            "fee_p90": [float(fee_range[5])],
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
