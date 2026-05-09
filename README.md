# general_monitor

A self-hosted, multi-topic analytics monitor. The first vertical is Bitcoin / mempool; networking and cybersecurity verticals are planned. Built as a portfolio piece — public dashboards on top of free APIs.

## Stack

- **UI / server:** Python Shiny
- **Storage:** DuckDB (single-file)
- **Data:** Polars
- **Plots:** Plotly
- **HTTP:** httpx

A long-running Shiny app reads from DuckDB and binds only to loopback. A separate ingester process writes to the DB on a schedule. In production, Caddy fronts the app with HTTPS, exposes dashboards publicly, and protects `/admin*` with Basic Auth. Cloudflare adds WAF and rate limiting on top.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python -m ingest.runner          # one ingest pass — writes to ./data.db
shiny run --reload app.py        # http://127.0.0.1:8000
```

## Schema

Append-only DuckDB. Table definitions live in `db.py::SCHEMA_STATEMENTS`. Schema migrations are additive (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` or new tables) — never `DROP`.

## Layout

```
general_monitor/
├── app.py                 # Shiny UI
├── db.py                  # DuckDB connection + schema
├── ingest/
│   ├── runner.py          # entrypoint: runs sources, logs to ingest_runs
│   └── sources/
│       └── mempool_space.py
├── requirements.txt
└── .env.example
```

## License

TBD.
