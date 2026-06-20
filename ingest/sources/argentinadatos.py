import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("ARGENTINADATOS_BASE", "https://api.argentinadatos.com/v1")
SOURCE_NAME = "argentinadatos.riesgo_pais"
INTERVAL_SECONDS = 3600

RIESGO_SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "valor": pl.Float64,
}

DOLAR_SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "casa": pl.Utf8,
    "compra": pl.Float64,
    "venta": pl.Float64,
}


def _day(fecha: str) -> datetime:
    return datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc)


def fetch(client: httpx.Client) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
    r = client.get(f"{BASE_URL}/finanzas/indices/riesgo-pais/ultimo", timeout=timeout)
    r.raise_for_status()
    d = r.json()
    return pl.DataFrame(
        {"ts": [_day(d["fecha"])], "valor": [float(d["valor"])]},
        schema=RIESGO_SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO riesgo_pais (ts, valor)
            SELECT ts, valor FROM _df
            ON CONFLICT (ts) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill_riesgo_pais(client: httpx.Client, conn) -> int:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    r = client.get(f"{BASE_URL}/finanzas/indices/riesgo-pais", timeout=timeout)
    r.raise_for_status()
    rows = [d for d in r.json() if d.get("valor") is not None]
    if not rows:
        return 0
    df = pl.DataFrame(
        {
            "ts": [_day(d["fecha"]) for d in rows],
            "valor": [float(d["valor"]) for d in rows],
        },
        schema=RIESGO_SCHEMA,
    )
    return upsert(conn, df)


def backfill_dolar(client: httpx.Client, conn) -> int:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    r = client.get(f"{BASE_URL}/cotizaciones/dolares", timeout=timeout)
    r.raise_for_status()
    rows = [d for d in r.json() if d.get("venta") is not None]
    if not rows:
        return 0
    df = pl.DataFrame(
        {
            "ts": [_day(d["fecha"]) for d in rows],
            "casa": [d["casa"] for d in rows],
            "compra": [d.get("compra") for d in rows],
            "venta": [float(d["venta"]) for d in rows],
        },
        schema=DOLAR_SCHEMA,
    )
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
