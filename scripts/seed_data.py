"""
Database/Cache Seeder
=====================

Purpose:
- Populate Postgres and Redis with canonical support data so toolbox queries
  return realistic results instead of mock placeholders.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies & Requirements:
- `asyncpg` for PostgreSQL operations
- `redis` client for caching
- `python-dotenv` for local env loading
- Environment variables: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `REDIS_URL`

Security Considerations:
- Do not hardcode credentials; use `.env` or platform secrets.
- Seed data may include PII (names/emails); restrict access appropriately.

Performance Considerations:
- Bulk inserts are executed sequentially; for large datasets, consider COPY/transaction batching.

Usage:
    source .venv/bin/activate
    set -a && source .env && set +a
    python scripts/seed_data.py

TODO:
- Add idempotent checks for existing data volumes beyond conflict upserts.
- Provide CLI flags for selective seeding (only Redis, only Postgres).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

import asyncpg
import redis
from dotenv import load_dotenv


CUSTOMERS = [
    {
        "id": "1",
        "name": "Alice Smith",
        "email": "alice@example.com",
        "tier": "gold",
        "status": "active",
    },
    {
        "id": "2",
        "name": "Marcus Lee",
        "email": "marcus@example.com",
        "tier": "silver",
        "status": "active",
    },
    {
        "id": "3",
        "name": "Priya Nair",
        "email": "priya@example.com",
        "tier": "platinum",
        "status": "vip",
    },
]


ORDERS = [
    {
        "id": "1001",
        "customer_id": "1",
        "status": "delivered",
        "total": 149.99,
        "created_at": "2024-10-05T14:30:00",
        "eta": "2024-10-10",
        "items": [
            {"name": "Noise-cancelling headphones", "qty": 1},
        ],
        "tracking_number": "1Z45A001XZ1001",
    },
    {
        "id": "1002",
        "customer_id": "1",
        "status": "processing",
        "total": 89.50,
        "created_at": "2024-10-12T09:18:00",
        "eta": "2024-10-18",
        "items": [
            {"name": "Smart home sensor kit", "qty": 1},
        ],
        "tracking_number": "1Z45A001XZ1002",
    },
    {
        "id": "2001",
        "customer_id": "2",
        "status": "shipped",
        "total": 59.00,
        "created_at": "2024-11-01T11:10:00",
        "eta": "2024-11-05",
        "items": [
            {"name": "Wireless charger", "qty": 2},
        ],
        "tracking_number": "1Z45B002XZ2001",
    },
    {
        "id": "3001",
        "customer_id": "3",
        "status": "delivered",
        "total": 249.00,
        "created_at": "2024-09-22T16:45:00",
        "eta": "2024-09-27",
        "items": [
            {"name": "Smart thermostat bundle", "qty": 1},
        ],
        "tracking_number": "1Z45C003XZ3001",
    },
]


def _load_env() -> None:
    """
    Load environment variables from a `.env` file when present.

    Returns:
    - None
    """
    load_dotenv(override=False)


async def seed_postgres() -> None:
    """
    Create tables and upsert canonical customers/orders into Postgres.

    Returns:
    - None

    Raises:
    - Propagates database connection errors if host/credentials are invalid.
    """
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "support_db")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "password")

    conn = await asyncpg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=name,
    )
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                tier TEXT,
                status TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_id TEXT REFERENCES customers(id),
                status TEXT,
                total NUMERIC(10, 2),
                created_at TIMESTAMPTZ,
                eta DATE,
                items JSONB,
                tracking_number TEXT
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_customer_created
                ON orders (customer_id, created_at DESC);
            """
        )

        # === Upsert Customers ===
        for customer in CUSTOMERS:
            await conn.execute(
                """
                INSERT INTO customers (id, name, email, tier, status)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    tier = EXCLUDED.tier,
                    status = EXCLUDED.status;
                """,
                customer["id"],
                customer["name"],
                customer["email"],
                customer["tier"],
                customer["status"],
            )

        # === Upsert Orders ===
        for order in ORDERS:
            await conn.execute(
                """
                INSERT INTO orders (id, customer_id, status, total, created_at, eta, items, tracking_number)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    total = EXCLUDED.total,
                    created_at = EXCLUDED.created_at,
                    eta = EXCLUDED.eta,
                    items = EXCLUDED.items,
                    tracking_number = EXCLUDED.tracking_number;
                """,
                order["id"],
                order["customer_id"],
                order["status"],
                order["total"],
                datetime.fromisoformat(order["created_at"]),
                datetime.fromisoformat(order["eta"]).date(),
                json.dumps(order["items"]),
                order["tracking_number"],
            )
    finally:
        await conn.close()


def seed_redis() -> None:
    """
    Seed Redis with canonical customer and order data, and index lists.

    Returns:
    - None
    """
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
    client = redis.Redis.from_url(url, decode_responses=True)

    # === Customer Hashes ===
    for customer in CUSTOMERS:
        key = f"support:customer:{customer['id']}"
        client.hset(
            key,
            mapping={
                "id": customer["id"],
                "name": customer["name"],
                "email": customer["email"],
                "tier": customer["tier"],
                "status": customer["status"],
            },
        )

    # === Order Hashes + Lookup Lists ===
    for order in ORDERS:
        order_key = f"support:order:{order['id']}"
        client.hset(
            order_key,
            mapping={
                "id": order["id"],
                "customer_id": order["customer_id"],
                "status": order["status"],
                "total": str(order["total"]),
                "created_at": order["created_at"],
                "eta": order["eta"],
                "items": json.dumps(order["items"]),
                "tracking_number": order["tracking_number"],
            },
        )

    # Maintain per-customer order lists (most recent first)
    orders_by_customer: dict[str, list[dict[str, str]]] = {}
    for order in ORDERS:
        orders_by_customer.setdefault(order["customer_id"], []).append(order)

    for customer in CUSTOMERS:
        list_key = f"support:orders:customer:{customer['id']}"
        client.delete(list_key)
        customer_orders = sorted(
            orders_by_customer.get(customer["id"], []),
            key=lambda o: o["created_at"],
            reverse=True,
        )
        order_ids = [order["id"] for order in customer_orders]
        if order_ids:
            client.rpush(list_key, *order_ids)


async def main() -> None:
    """
    Entrypoint that loads env, seeds Postgres and Redis, and reports completion.

    Returns:
    - None

    Example:
    ```bash
    source .venv/bin/activate
    set -a && source .env && set +a
    python scripts/seed_data.py
    ```
    """
    _load_env()
    await seed_postgres()
    seed_redis()
    print("✅ Seed complete: Postgres tables and Redis keys populated.")


if __name__ == "__main__":
    asyncio.run(main())
