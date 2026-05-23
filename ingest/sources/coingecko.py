import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("COINGECKO_BASE", "https://api.coingecko.com/api/v3")
SOURCE_NAME = "coingecko.prices"
INTERVAL_SECONDS = 60

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "source": pl.Utf8,
    "pair": pl.Utf8,
    "price": pl.Float64,
}


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(
        f"{BASE_URL}/simple/price",
        params={"ids": "bitcoin", "vs_currencies": "usd"},
        timeout=timeout,
    )
    r.raise_for_status()
    price = float(r.json()["bitcoin"]["usd"])
    return pl.DataFrame(
        {
            "ts": [datetime.now(tz=timezone.utc)],
            "source": ["coingecko"],
            "pair": ["BTC/USD"],
            "price": [price],
        },
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO prices (ts, source, pair, price)
            SELECT ts, source, pair, price FROM _df
            ON CONFLICT (ts, source, pair) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(client: httpx.Client, conn, days: int = 30) -> int:
    # CoinGecko free: days<=1 → 5-min granularity, 2-90 → hourly, >90 → daily.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    r = client.get(
        f"{BASE_URL}/coins/bitcoin/market_chart",
        params={"vs_currency": "usd", "days": days},
        timeout=timeout,
    )
    r.raise_for_status()
    pairs = r.json().get("prices", [])
    if not pairs:
        return 0
    df = pl.DataFrame(
        {
            "ts": [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in pairs],
            "source": ["coingecko"] * len(pairs),
            "pair": ["BTC/USD"] * len(pairs),
            "price": [float(p[1]) for p in pairs],
        },
        schema=SCHEMA,
    )
    return upsert(conn, df)
