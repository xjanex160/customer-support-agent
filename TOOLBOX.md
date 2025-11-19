# Using genai-toolbox with this project

This project now targets the `genai-toolbox` format for MCP tools (see https://googleapis.github.io/genai-toolbox/). The provided `tools.yaml` describes the Postgres and Redis tools the agent needs.

## Setup

1) Ensure you have the toolbox binary (you already downloaded `/Users/ebubeimoh/toolbox`). If needed, make it executable: `chmod +x ~/toolbox`.
2) Export connection env vars (defaults are fine for local Docker-based DB/Redis):
```sh
export DB_HOST=127.0.0.1
export DB_PORT=5432
export DB_NAME=support_db
export DB_USER=postgres
export DB_PASSWORD=password
export REDIS_ADDRESS=127.0.0.1:6379
export REDIS_URL=redis://127.0.0.1:6379

# Seed Postgres + Redis
python scripts/seed_data.py
```
3) Start the toolbox server pointing at the bundled tools file:
```sh
~/toolbox --tools-file tools.yaml --port 5000
```
   (Add `--disable-reload` if you don’t want it to watch for file changes.)

## Tool definition highlights (`tools.yaml`)
- Sources: `support-postgres` and `support-redis` point to your DB/Redis.
- Tools:
  - `recent-orders` / `customer-profile` (Postgres SQL queries)
  - `redis-get-cache` / `redis-set-cache` (Redis GET/SETEX)
- Toolset: `support-toolset` groups those tools.

## Application env
- The FastAPI support app reads `OPENAI_API_KEY` for LLM calls.
- The agent talks to toolbox at `TOOLBOX_BASE_URL` (default `http://127.0.0.1:5000`) and uses the `support-toolset`.

## Running everything locally
```sh
# Install deps
uv pip install -r requirements.txt

# Start toolbox (separate terminal)
~/toolbox --tools-file tools.yaml --port 5000

# Start support API
uvicorn app.main:app --reload --port 8000
```

Then hit `POST http://localhost:8000/support` with `{"query": "...", "customer_id": "1"}` or run `python tests/test_agent.py`.
