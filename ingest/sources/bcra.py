import os
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import polars as pl

BASE_URL = os.environ.get("BCRA_BASE", "https://api.bcra.gob.ar/estadisticas/v4.0")
SOURCE_NAME = "bcra.monetarias"
INTERVAL_SECONDS = 21600
PAGE_LIMIT = 3000
LIVE_WINDOW_DAYS = 120

# (series key, BCRA idVariable)
SERIES = (
    ("reservas", 1),
    ("inflacion_mensual", 27),
    ("inflacion_interanual", 28),
    ("inflacion_esperada", 29),
)

SCHEMA = {
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "series": pl.Utf8,
    "source": pl.Utf8,
    "value": pl.Float64,
}


def _get(client: httpx.Client, var_id: int, params: dict) -> tuple[list, int]:
    timeout = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
    r = client.get(f"{BASE_URL}/monetarias/{var_id}", params=params, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    results = body.get("results") or []
    rows = results[0]["detalle"] if results else []
    return rows, body["metadata"]["resultset"]["count"]


def _to_df(key: str, rows: list) -> pl.DataFrame:
    rows = [r for r in rows if r.get("valor") is not None]
    return pl.DataFrame(
        {
            "ts": [
                datetime.fromisoformat(r["fecha"]).replace(tzinfo=timezone.utc) for r in rows
            ],
            "series": [key] * len(rows),
            "source": ["bcra"] * len(rows),
            "value": [float(r["valor"]) for r in rows],
        },
        schema=SCHEMA,
    )


def fetch(client: httpx.Client) -> pl.DataFrame:
    desde = (date.today() - timedelta(days=LIVE_WINDOW_DAYS)).isoformat()
    frames = []
    for key, var_id in SERIES:
        rows, _ = _get(client, var_id, {"desde": desde, "limit": PAGE_LIMIT})
        frames.append(_to_df(key, rows))
    return pl.concat(frames)


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


def backfill(client: httpx.Client, conn, sleep_s: float = 0.5) -> int:
    inserted = 0
    for key, var_id in SERIES:
        offset = 0
        while True:
            rows, total = _get(client, var_id, {"limit": PAGE_LIMIT, "offset": offset})
            if rows:
                inserted += upsert(conn, _to_df(key, rows))
            offset += PAGE_LIMIT
            if not rows or offset >= total:
                break
            time.sleep(sleep_s)
    return inserted
