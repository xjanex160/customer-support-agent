# Customer Support Agent (genai-toolbox)

An LLM-powered customer support service wired to a genai-toolbox toolset (Postgres + Redis) with FastAPI. The agent routes user queries to database lookups, cached answers, or LLM generation, and the toolbox server exposes the underlying tools.

## What's included
- `app/agent.py`: query routing, caching, fallback responses, OpenAI integration.
- `app/mcp_client.py`: talks to the toolbox server (`toolbox_core`) and falls back to in-memory mocks.
- `app/main.py`: FastAPI app exposing `POST /support` and `/health`.
- `tools.yaml`: toolbox configuration for Postgres/Redis tools and the `support-toolset`.
- `TOOLBOX.md`: toolbox-specific run instructions.
- OpenAI Agents SDK (`openai-agents`) drives LLM responses; set `OPENAI_API_KEY` (and optionally `OPENAI_BASE_URL`/`AGENT_MODEL`) to control the backing model.

## Prereqs
- Python 3.9+
- Redis running locally (defaults to `127.0.0.1:6379`).
- Postgres running locally with a database `support_db` and user `postgres/password` (configurable via env).
- Tooling binary: `~/toolbox` (genai-toolbox) already downloaded.

## Install deps
```sh
# (recommended) create/use the project venv
uv init  # if you haven't already; creates .venv and pyproject for uv

# install dependencies into .venv
uv pip install -r requirements.txt
```

## Quick start
1. Copy `.env.example` to `.env`, then fill in the values for database, Redis, and your model provider. To target Google Gemini, use:
   ```sh
   OPENAI_API_KEY="$GOOGLE_API_KEY"
   OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
   AGENT_MODEL="gemini-2.5-flash"
   TAVILY_API_KEY=your_tavily_key
    MEMORY_REDIS_URL="redis://127.0.0.1:6379"
   ```
2. Activate the virtualenv and export env vars (run this in **every** shell before starting services):
   ```sh
   cd ~/Documents/projects/customer-support-agent
   source .venv/bin/activate
   set -a && source .env && set +a
   ```
3. Start dependencies:
   ```sh
   # Postgres (brew example)
   brew services start postgresql@15
   createdb -h 127.0.0.1 -p 5432 -U postgres support_db

   # Redis
   redis-server --port 6379
   ```
4. Seed Postgres + Redis with sample support data:
   ```sh
   python scripts/seed_data.py
   ```
5. Launch toolbox in its own terminal:
   ```sh
   ~/toolbox --tools-file tools.yaml --port 5000
   ```
6. Launch the FastAPI app in another terminal:
   ```sh
   source .venv/bin/activate
   set -a && source .env && set +a
   TOOLBOX_BASE_URL=http://127.0.0.1:5000 uvicorn app.main:app --reload --port 8000
   ```
7. Interact with the agent:
   ```sh
   curl -X POST http://127.0.0.1:8000/support \
     -H "Content-Type: application/json" \
     -d '{"query": "What are my recent orders?", "customer_id": "1", "session_id": "cust-1-session"}'
   ```
   or
   ```sh
   python tests/test_agent.py
   ```

## Redis sample data (loaded)
The Redis instance is pre-seeded with support-oriented keys after running `python scripts/seed_data.py`:
- Customers: `support:customer:1..3`
- Orders: `support:order:1001`, `support:order:1002`, `support:order:2001`, `support:order:3001`
- Order lists per customer: `support:orders:customer:<id>`
- Cached FAQ/last response: `support:cache:*`

Useful checks:
```sh
redis-cli KEYS 'support:*'
redis-cli HGETALL support:customer:1
redis-cli LRANGE support:orders:customer:1 0 -1
redis-cli LRANGE support:memory:cust-1-session 0 -1  # conversation memory
```

## Conversation memory
- Each `/support` call can include an optional `session_id`. When provided (or inferred from `customer_id`), the agent stores the most recent turns in Redis (`support:memory:<session>`). Those turns are added to the next prompt so the LLM has conversational context.
- Clear session memory with `redis-cli DEL support:memory:<session>`.
- Gradio (`python main.py`) exposes separate Customer ID and Session ID fields so you can experiment with different sessions without restarting services.

## Troubleshooting
- **`toolbox failed to initialize: environment variable not found`** – run `set -a && source .env && set +a` in every terminal before launching toolbox/uvicorn so `${DB_*}`/`${REDIS_*}` placeholders resolve.
- **`unable to connect ... user=postgres database=support_db`** – start Postgres (`brew services start postgresql@15` or `pg_ctl ... start`) and ensure `support_db` exists. Verify with `pg_isready` or `psql postgres://postgres:password@127.0.0.1:5432/support_db`.
- **`unable to connect to redis ... connect: connection refused`** – start Redis (`redis-server --port 6379` or `brew services start redis`) and confirm `REDIS_ADDRESS`/`REDIS_URL` point at the running instance.
- **Agent always replies “I'll help you with that...”** – the LLM fallback cached because no API key was available or the provider rejected it. Clear Redis (`redis-cli KEYS 'support:*' | xargs redis-cli DEL ...`) and ensure `OPENAI_API_KEY`/`OPENAI_BASE_URL` are exported before restarting.
- **`Error getting response: 404` or `invalid_api_key`** – when using Gemini, the key must be OpenAI-compatible. The included `OpenAIProvider` handles this if you follow the `.env` instructions above; with a real OpenAI key, leave `OPENAI_BASE_URL` unset.
