# general_monitor

A self-hosted, multi-topic analytics monitor. The first vertical is Bitcoin / mempool; networking and cybersecurity verticals are planned. Public dashboards on top of free APIs.

## Stack

- **UI / server:** Python Shiny
- **Storage:** DuckDB
- **Data:** Polars
- **Plots:** Plotly
- **HTTP:** httpx


## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python -m ingest.runner                            # one ingest pass — writes to ./data.db
uvicorn app:app --host 127.0.0.1 --port 8000 --reload   # http://127.0.0.1:8000
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
├── requirements.txt
└── .env.example
```

## License

TBD.
