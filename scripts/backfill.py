"""Backfill historical data for sources that expose it.

Usage:
    python -m scripts.backfill all --days 30
    python -m scripts.backfill prices --days 30
    python -m scripts.backfill network --days 30
    python -m scripts.backfill blocks --hours 720
    python -m scripts.backfill prices_history
    python -m scripts.backfill tx_history
    python -m scripts.backfill dolar_history
    python -m scripts.backfill riesgo_pais_history
    python -m scripts.backfill usdc_history
"""
import argparse
import os
import sys
import time

import httpx

from db import get_conn, init_schema
from ingest.sources import argentinadatos, blockchain_info, coingecko, defillama
from ingest.sources.mempool_space import blocks as mp_blocks

TARGETS = (
    "prices",
    "prices_history",
    "tx_history",
    "network",
    "blocks",
    "dolar_history",
    "riesgo_pais_history",
    "usdc_history",
    "all",
)


def _client() -> httpx.Client:
    ua = os.environ.get("INGEST_USER_AGENT", "general_monitor/0.1")
    return httpx.Client(headers={"User-Agent": ua})


def _run_prices(conn, client, days: int) -> int:
    t0 = time.monotonic()
    n = coingecko.backfill(client, conn, days=days)
    print(f"prices: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_prices_history(conn, client) -> int:
    t0 = time.monotonic()
    n = blockchain_info.backfill_market_price(client, conn)
    print(f"prices (history): inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_tx_history(conn, client) -> int:
    t0 = time.monotonic()
    n = blockchain_info.backfill_n_transactions(client, conn)
    print(f"tx_history: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_network(conn, client, days: int) -> int:
    t0 = time.monotonic()
    # blockchain.info accepts e.g. "30days", "180days", "1year", "all"
    timespan = f"{days}days"
    n = blockchain_info.backfill(client, conn, timespan=timespan)
    print(f"network_stats: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_blocks(conn, client, hours: int) -> int:
    t0 = time.monotonic()
    n = mp_blocks.backfill(client, conn, hours=hours)
    print(f"blocks: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_dolar_history(conn, client) -> int:
    t0 = time.monotonic()
    n = argentinadatos.backfill_dolar(client, conn)
    print(f"dolar_history: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_riesgo_pais_history(conn, client) -> int:
    t0 = time.monotonic()
    n = argentinadatos.backfill_riesgo_pais(client, conn)
    print(f"riesgo_pais_history: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def _run_usdc_history(conn, client) -> int:
    t0 = time.monotonic()
    n = defillama.backfill(client, conn)
    print(f"usdc_history: inserted {n} rows in {time.monotonic() - t0:.1f}s")
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--days", type=int, default=30, help="window in days (prices, network)")
    parser.add_argument("--hours", type=int, default=720, help="window in hours (blocks)")
    args = parser.parse_args()

    init_schema()
    conn = get_conn(readonly=False)
    client = _client()
    failures = 0
    try:
        if args.target in ("prices", "all"):
            try:
                _run_prices(conn, client, args.days)
            except Exception as e:
                print(f"prices failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target == "prices_history":
            try:
                _run_prices_history(conn, client)
            except Exception as e:
                print(f"prices_history failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target == "tx_history":
            try:
                _run_tx_history(conn, client)
            except Exception as e:
                print(f"tx_history failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target in ("network", "all"):
            try:
                _run_network(conn, client, args.days)
            except Exception as e:
                print(f"network failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target in ("blocks", "all"):
            try:
                _run_blocks(conn, client, args.hours)
            except Exception as e:
                print(f"blocks failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target == "dolar_history":
            try:
                _run_dolar_history(conn, client)
            except Exception as e:
                print(f"dolar_history failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target == "riesgo_pais_history":
            try:
                _run_riesgo_pais_history(conn, client)
            except Exception as e:
                print(f"riesgo_pais_history failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
        if args.target == "usdc_history":
            try:
                _run_usdc_history(conn, client)
            except Exception as e:
                print(f"usdc_history failed: {type(e).__name__}: {e}", file=sys.stderr)
                failures += 1
    finally:
        client.close()
        conn.close()
    return failures


if __name__ == "__main__":
    sys.exit(main())
