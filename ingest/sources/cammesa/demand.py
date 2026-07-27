import os
import time
from datetime import date, datetime, timedelta

import httpx
import polars as pl

BASE_URL = os.environ.get("CAMMESA_BASE", "https://api.cammesa.com")
SOURCE_NAME = "cammesa.demand"
# Scheduled externally by monitor-cammesa.timer alongside generation (once daily).
INTERVAL_SECONDS = 0
REGION_SADI = 1002

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "region": pl.Int32,
    "dem": pl.Float64,
    "temp": pl.Float64,
}


def _to_df(rows: list[dict], region: int) -> pl.DataFrame:
    rows = [r for r in rows if r.get("fecha")]
    return pl.DataFrame(
        {
            "ts": [datetime.fromisoformat(r["fecha"]) for r in rows],
            "region": [region] * len(rows),
            "dem": [r.get("dem") for r in rows],
            "temp": [r.get("temp") for r in rows],
        },
        schema=SCHEMA,
    )


def fetch(client: httpx.Client, region: int = REGION_SADI) -> pl.DataFrame:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
    r = client.get(
        f"{BASE_URL}/demanda-svc/demanda/ObtieneDemandaYTemperaturaRegion",
        params={"id_region": region},
        timeout=timeout,
    )
    r.raise_for_status()
    # The "today" endpoint names its actual reading demHoy/tempHoy, unlike the
    # ByFecha variant (dem/temp) that backfill hits and that _to_df expects.
    rows = r.json()
    for row in rows:
        row["dem"] = row.get("demHoy")
        row["temp"] = row.get("tempHoy")
    return _to_df(rows, region)


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO cammesa_demand (ts, region, dem, temp)
            SELECT ts, region, dem, temp FROM _df
            ON CONFLICT (ts, region) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height


def backfill(
    client: httpx.Client,
    conn,
    days: int = 30,
    region: int = REGION_SADI,
    sleep_s: float = 1.0,
) -> int:
    # Unlike generation, the ByFecha demand endpoint honors `fecha`, so we iterate
    # backwards day by day (~288 5-min points each) from yesterday.
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))
    inserted = 0
    day = date.today() - timedelta(days=1)
    for _ in range(days):
        r = client.get(
            f"{BASE_URL}/demanda-svc/demanda/ObtieneDemandaYTemperaturaRegionByFecha",
            params={"id_region": region, "fecha": day.isoformat()},
            timeout=timeout,
        )
        r.raise_for_status()
        rows = r.json()
        if rows:
            inserted += upsert(conn, _to_df(rows, region))
        day -= timedelta(days=1)
        time.sleep(sleep_s)
    return inserted
