import os
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "./data.db")

# DuckDB is single-writer across processes: while the ingester/backfill holds the
# write lock, read-only opens fail. Live writes are sub-second, so a short retry
# makes the overlap invisible; longer writes (backfills) fall through to DBBusy
# and the UI degrades gracefully instead of showing a stack trace.
RO_RETRIES = int(os.environ.get("DB_RO_RETRIES", "4"))
RO_RETRY_DELAY = float(os.environ.get("DB_RO_RETRY_DELAY", "0.25"))


class DBBusy(Exception):
    """A read-only connection couldn't be acquired: a writer holds the lock."""


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS mempool_snapshots (
        ts            TIMESTAMPTZ NOT NULL,
        tx_count      INTEGER     NOT NULL,
        vsize         BIGINT      NOT NULL,
        total_fee_btc DOUBLE      NOT NULL,
        fee_p10       DOUBLE,
        fee_p50       DOUBLE,
        fee_p90       DOUBLE,
        PRIMARY KEY (ts)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS blocks (
        height        INTEGER     PRIMARY KEY,
        hash          VARCHAR     NOT NULL UNIQUE,
        ts            TIMESTAMPTZ NOT NULL,
        tx_count      INTEGER     NOT NULL,
        size          BIGINT      NOT NULL,
        weight        BIGINT      NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tx_history (
        ts     TIMESTAMPTZ NOT NULL,
        source VARCHAR     NOT NULL,
        n_tx   BIGINT      NOT NULL,
        PRIMARY KEY (ts, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        ts     TIMESTAMPTZ NOT NULL,
        source VARCHAR     NOT NULL,
        pair   VARCHAR     NOT NULL,
        price  DOUBLE      NOT NULL,
        PRIMARY KEY (ts, source, pair)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes_snapshots (
        ts            TIMESTAMPTZ NOT NULL,
        total_nodes   INTEGER     NOT NULL,
        top_versions  JSON,
        PRIMARY KEY (ts)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ingest_runs (
        ts         TIMESTAMPTZ NOT NULL,
        source     VARCHAR     NOT NULL,
        status     VARCHAR     NOT NULL,
        latency_ms INTEGER,
        error      VARCHAR,
        PRIMARY KEY (ts, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS network_stats (
        ts            TIMESTAMPTZ NOT NULL,
        source        VARCHAR     NOT NULL,
        hash_rate_ehs DOUBLE,
        difficulty    DOUBLE,
        PRIMARY KEY (ts, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dolar_rates (
        ts     TIMESTAMPTZ NOT NULL,
        casa   VARCHAR     NOT NULL,
        compra DOUBLE,
        venta  DOUBLE      NOT NULL,
        PRIMARY KEY (ts, casa)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS riesgo_pais (
        ts    TIMESTAMPTZ NOT NULL,
        valor DOUBLE      NOT NULL,
        PRIMARY KEY (ts)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS usdc_supply (
        ts          TIMESTAMPTZ NOT NULL,
        circulating DOUBLE      NOT NULL,
        price       DOUBLE,
        PRIMARY KEY (ts)
    );
    """,
)


def get_conn(readonly: bool = False) -> duckdb.DuckDBPyConnection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if not readonly:
        conn = duckdb.connect(DB_PATH, read_only=False)
        conn.execute("SET TimeZone='UTC'")
        return conn
    last = None
    for attempt in range(RO_RETRIES):
        try:
            conn = duckdb.connect(DB_PATH, read_only=True)
            conn.execute("SET TimeZone='UTC'")
            return conn
        except duckdb.IOException as e:
            if "lock" not in str(e).lower():
                raise
            last = e
            if attempt < RO_RETRIES - 1:
                time.sleep(RO_RETRY_DELAY * (attempt + 1))
    raise DBBusy(str(last))


def init_schema() -> None:
    conn = get_conn(readonly=False)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
    finally:
        conn.close()
