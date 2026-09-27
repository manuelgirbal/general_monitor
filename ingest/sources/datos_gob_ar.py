import os
from datetime import datetime, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("DATOS_GOB_AR_BASE", "https://apis.datos.gob.ar/series/api")
SOURCE_NAME = "datos_gob_ar.series"
INTERVAL_SECONDS = 86400

# (series key, datos.gob.ar id, months to shift the index back).
# The EPH poverty dataset stamps each semester with the day after it ends
# (2024-07-01 = 1S2024), unlike the other series, which use the period start.
SERIES = (
    ("pobreza", "64.2_POBLACION_NUA_0_0_34_74", 6),
    ("gini", "65.1_CGI_0_0_21", 0),
    ("desocupacion", "42.3_EPH_PUNTUATAL_0_M_30", 0),
    ("icc", "380.3_ICC_NACIONNAL_0_T_12", 0),
    ("icg", "370.3_ICG_NIVEL_RAL_0_0_17_94", 0),
)

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "series": pl.Utf8,
    "source": pl.Utf8,
    "value": pl.Float64,
}


def _shift_months(d: datetime, months: int) -> datetime:
    total = d.year * 12 + (d.month - 1) - months
    return d.replace(year=total // 12, month=total % 12 + 1)


def _fetch_series(client: httpx.Client, series_id: str, timeout: float) -> list:
    # One request per id: mixing frequencies in one call makes the API aggregate
    # everything down to the lowest one.
    r = client.get(
        f"{BASE_URL}/series/",
        params={"ids": series_id, "format": "json", "limit": 5000},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["data"]


def fetch(client: httpx.Client) -> pl.DataFrame:
    # Each series is small (< 400 points), so every run pulls the full history:
    # gaps heal on their own and no separate backfill is needed.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
    ts, keys, values = [], [], []
    for key, series_id, shift in SERIES:
        for fecha, value in _fetch_series(client, series_id, timeout):
            if value is None:
                continue
            d = datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc)
            ts.append(_shift_months(d, shift))
            keys.append(key)
            values.append(float(value))
    return pl.DataFrame(
        {"ts": ts, "series": keys, "source": ["datos.gob.ar"] * len(ts), "value": values},
        schema=SCHEMA,
    )


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO macro_series (ts, series, source, value)
            SELECT ts, series, source, value FROM _df
            ON CONFLICT (ts, series) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height
