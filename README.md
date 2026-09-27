# general_monitor

A self-hosted, multi-topic analytics monitor. The first vertical is Bitcoin / mempool; networking and cybersecurity verticals are planned. Public dashboards on top of free APIs.

## Stack

- **UI / server:** Python Shiny
- **Storage:** DuckDB
- **Data:** Polars
- **Plots:** Plotly
- **HTTP:** httpx
- **Packaging:** [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`)


## Local dev

```bash
uv sync                                            # creates .venv from uv.lock
cp .env.example .env

uv run python -m ingest.runner                     # one ingest pass — writes to ./data.db
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload   # http://127.0.0.1:8000
```

The app is a Starlette parent that mounts two Shiny apps: the public dashboard at `/` and an admin panel at `/admin` (intended to sit behind Caddy Basic Auth in production).

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
│       └── mempool_space/
├── pyproject.toml         # dependencies (uv)
├── uv.lock
└── .env.example
```

## License

TBD.
