import os
from datetime import datetime

import httpx
import polars as pl

BASE_URL = os.environ.get("DOLARAPI_BASE", "https://dolarapi.com/v1")
SOURCE_NAME = "dolarapi.dolar"
INTERVAL_SECONDS = 300

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "casa": pl.Utf8,
    "compra": pl.Float64,
    "venta": pl.Float64,
}


def fetch(client: httpx.Client) -> pl.DataFrame:
    # ts = each quote's own fechaActualizacion → idempotent: unchanged quotes
    # re-insert the same (ts, casa) key and get dropped by ON CONFLICT.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/dolares", timeout=timeout)
    r.raise_for_status()
    rows = r.json()
    return pl.DataFrame(
        {
            "ts": [datetime.fromisoformat(d["fechaActualizacion"]) for d in rows],
            "casa": [d["casa"] for d in rows],
            "compra": [d.get("compra") for d in rows],
            "venta": [d["venta"] for d in rows],
        },
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO dolar_rates (ts, casa, compra, venta)
            SELECT ts, casa, compra, venta FROM _df
            ON CONFLICT (ts, casa) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height
