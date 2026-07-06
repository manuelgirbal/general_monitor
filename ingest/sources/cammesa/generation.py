import os
from datetime import datetime

import httpx
import polars as pl

BASE_URL = os.environ.get("CAMMESA_BASE", "https://api.cammesa.com")
SOURCE_NAME = "cammesa.generation"
# Scheduled externally by monitor-cammesa.timer (once daily, late in the AR day): the
# endpoint returns only the current day up to now and can't backfill, so a single late
# fetch captures the near-complete curve. No self-throttle here.
INTERVAL_SECONDS = 0
REGION_SADI = 1002

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "region": pl.Int32,
    "total": pl.Float64,
    "hidraulico": pl.Float64,
    "termico": pl.Float64,
    "nuclear": pl.Float64,
    "renovable": pl.Float64,
    "importacion": pl.Float64,
}


def _to_df(rows: list[dict], region: int) -> pl.DataFrame:
    rows = [r for r in rows if r.get("fecha")]
    return pl.DataFrame(
        {
            "ts": [datetime.fromisoformat(r["fecha"]) for r in rows],
            "region": [region] * len(rows),
            "total": [r.get("sumTotal") for r in rows],
            "hidraulico": [r.get("hidraulico") for r in rows],
            "termico": [r.get("termico") for r in rows],
            "nuclear": [r.get("nuclear") for r in rows],
            "renovable": [r.get("renovable") for r in rows],
            "importacion": [r.get("importacion") for r in rows],
        },
        schema=SCHEMA,
    )


def fetch(client: httpx.Client, region: int = REGION_SADI) -> pl.DataFrame:
    # Only returns the current day's 5-min curve; the `fecha` param is ignored, so there
    # is no history here. Re-running the same day only adds new points (ON CONFLICT).
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
    r = client.get(
        f"{BASE_URL}/demanda-svc/generacion/ObtieneGeneracioEnergiaPorRegion",
        params={"id_region": region},
        timeout=timeout,
    )
    r.raise_for_status()
    return _to_df(r.json(), region)


def upsert(conn, df: pl.DataFrame) -> int:
    conn.register("_df", df)
    try:
        conn.execute(
            """
            INSERT INTO cammesa_generation
                (ts, region, total, hidraulico, termico, nuclear, renovable, importacion)
            SELECT ts, region, total, hidraulico, termico, nuclear, renovable, importacion
            FROM _df
            ON CONFLICT (ts, region) DO NOTHING
            """
        )
    finally:
        conn.unregister("_df")
    return df.height
