import os
import time
from datetime import datetime, timezone

import httpx
import polars as pl

# Unofficial public chart endpoint: free and keyless, but undocumented and
# unsupported. Treat as fragile (hourly polling, one request per symbol).
BASE_URL = os.environ.get("YAHOO_CHART_BASE", "https://query1.finance.yahoo.com/v8/finance/chart")
SOURCE_NAME = "yahoo.markets"
INTERVAL_SECONDS = 3600

SYMBOLS = ("^GSPC", "HG=F", "GC=F", "BZ=F", "NG=F")

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "symbol": pl.Utf8,
    "close": pl.Float64,
}


def _fetch_symbol(client: httpx.Client, symbol: str, params: dict) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
    r = client.get(f"{BASE_URL}/{symbol}", params={**params, "interval": "1d"}, timeout=timeout)
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    offset = int(result["meta"].get("gmtoffset") or 0)
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    ts, values = [], []
    for t, c in zip(stamps, closes):
        if c is None:
            continue
        # Key each bar by its trading date in the exchange's timezone.
        day = datetime.fromtimestamp(t + offset, tz=timezone.utc).date()
        ts.append(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))
        values.append(float(c))
    return pl.DataFrame(
        {"ts": ts, "symbol": [symbol] * len(ts), "close": values}, schema=SCHEMA
    ).unique(subset=["ts", "symbol"], keep="last")


def fetch(client: httpx.Client) -> pl.DataFrame:
    return pl.concat([_fetch_symbol(client, s, {"range": "1mo"}) for s in SYMBOLS])


def upsert(conn, df: pl.DataFrame) -> int:
    # The current day's bar keeps moving until the session closes, so this table
    # updates the close for an existing (day, symbol) instead of ignoring it.
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO market_daily (ts, symbol, close)
            SELECT ts, symbol, close FROM _df
            ON CONFLICT (ts, symbol) DO UPDATE SET close = excluded.close
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(client: httpx.Client, conn, sleep_s: float = 1.0) -> int:
    inserted = 0
    now = int(time.time())
    for symbol in SYMBOLS:
        df = _fetch_symbol(client, symbol, {"period1": 0, "period2": now})
        inserted += upsert(conn, df)
        time.sleep(sleep_s)
    return inserted
