import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("DEFILLAMA_STABLECOINS_BASE", "https://stablecoins.llama.fi")
SOURCE_NAME = "defillama.usdc"
INTERVAL_SECONDS = 3600
USDC_ID = 2

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "circulating": pl.Float64,
    "price": pl.Float64,
}


def _peg(obj) -> float:
    return float(obj["peggedUSD"])


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
    r = client.get(f"{BASE_URL}/stablecoins", params={"includePrices": "true"}, timeout=timeout)
    r.raise_for_status()
    usdc = next(s for s in r.json()["peggedAssets"] if int(s["id"]) == USDC_ID)
    price = usdc.get("price")
    return pl.DataFrame(
        {
            "ts": [datetime.now(tz=timezone.utc)],
            "circulating": [_peg(usdc["circulating"])],
            "price": [None if price is None else float(price)],
        },
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO usdc_supply (ts, circulating, price)
            SELECT ts, circulating, price FROM _df
            ON CONFLICT (ts) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(client: httpx.Client, conn) -> int:
    # Daily circulating-supply series since 2018; no price in this endpoint.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    r = client.get(
        f"{BASE_URL}/stablecoincharts/all",
        params={"stablecoin": USDC_ID},
        timeout=timeout,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return 0
    df = pl.DataFrame(
        {
            "ts": [datetime.fromtimestamp(int(d["date"]), tz=timezone.utc) for d in rows],
            "circulating": [_peg(d["totalCirculating"]) for d in rows],
            "price": [None] * len(rows),
        },
        schema=SCHEMA,
    )
    return upsert(conn, df)
