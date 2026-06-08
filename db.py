import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "./data.db")


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
)


def get_conn(readonly: bool = False) -> duckdb.DuckDBPyConnection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(DB_PATH, read_only=readonly)
    conn.execute("SET TimeZone='UTC'")
    return conn


def init_schema() -> None:
    conn = get_conn(readonly=False)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
    finally:
        conn.close()
