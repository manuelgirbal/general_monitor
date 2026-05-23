import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("BLOCKCHAIN_INFO_BASE", "https://api.blockchain.info")
SOURCE_NAME = "blockchain_info.network"
INTERVAL_SECONDS = 3600

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "source": pl.Utf8,
    "hash_rate_ehs": pl.Float64,
    "difficulty": pl.Float64,
}


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/stats", timeout=timeout)
    r.raise_for_status()
    data = r.json()
    # blockchain.info /stats returns hash_rate in GH/s
    hash_rate_ehs = float(data["hash_rate"]) / 1e9
    difficulty = float(data["difficulty"])
    return pl.DataFrame(
        {
            "ts": [datetime.now(tz=timezone.utc)],
            "source": ["blockchain_info"],
            "hash_rate_ehs": [hash_rate_ehs],
            "difficulty": [difficulty],
        },
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO network_stats (ts, source, hash_rate_ehs, difficulty)
            SELECT ts, source, hash_rate_ehs, difficulty FROM _df
            ON CONFLICT (ts, source) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(client: httpx.Client, conn, timespan: str = "30days") -> int:
    # blockchain.info charts return TH/s for hash-rate (different unit from /stats which is GH/s).
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    r1 = client.get(
        f"{BASE_URL}/charts/hash-rate",
        params={"timespan": timespan, "format": "json"},
        timeout=timeout,
    )
    r1.raise_for_status()
    r2 = client.get(
        f"{BASE_URL}/charts/difficulty",
        params={"timespan": timespan, "format": "json"},
        timeout=timeout,
    )
    r2.raise_for_status()

    hash_points = {int(p["x"]): float(p["y"]) for p in r1.json().get("values", [])}
    diff_points = {int(p["x"]): float(p["y"]) for p in r2.json().get("values", [])}
    timestamps = sorted(set(hash_points) | set(diff_points))
    if not timestamps:
        return 0

    df = pl.DataFrame(
        {
            "ts": [datetime.fromtimestamp(t, tz=timezone.utc) for t in timestamps],
            "source": ["blockchain_info"] * len(timestamps),
            "hash_rate_ehs": [
                (hash_points[t] / 1e6) if t in hash_points else None
                for t in timestamps
            ],
            "difficulty": [diff_points.get(t) for t in timestamps],
        },
        schema=SCHEMA,
    )
    return upsert(conn, df)
