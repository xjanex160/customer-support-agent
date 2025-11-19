"""
Redis-backed conversation memory
================================

Purpose:
- Provide a lightweight helper to store and retrieve recent conversation turns
  in Redis for contextual replies.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies & Requirements:
- `redis.asyncio` client for async Redis operations
- Environment variable `REDIS_URL` (recommended) for connection string

Security Considerations:
- Conversation content may include PII; apply retention policies and restrict access.
- Consider encryption at rest and content sanitization for sensitive fields.

Performance Considerations:
- Uses lists with trimming to limit memory footprint; keep `max_turns` modest.

TODO:
- Add optional compression for entries to reduce Redis memory.
- Integrate per-session quotas and basic rate limiting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis import asyncio as aioredis


class RedisConversationMemory:
    """
    Lightweight helper that stores recent conversation turns in Redis.

    Parameters:
    - url: `str` Redis connection URL (e.g., `redis://127.0.0.1:6379`).
    - ttl_seconds: `int` expiration for the conversation list.
    - max_turns: `int` number of recent turns to keep (approximate; two entries per turn).
    - prefix: `str` key prefix used for namespacing.

    Notes:
    - Each turn typically includes a user and assistant message, hence 2 entries.
    """

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 60 * 60 * 24,
        max_turns: int = 10,
        prefix: str = "support:memory",
    ) -> None:
        self._client = aioredis.from_url(url, decode_responses=True)
        self._ttl = ttl_seconds
        self._max_turns = max_turns
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        """Return the Redis key for a given session id."""
        return f"{self._prefix}:{session_id}"

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        """
        Append a single message to the conversational memory.

        Parameters:
        - session_id: `str` unique session identifier.
        - role: `str` message role (e.g., `user`, `assistant`).
        - content: `str` message content.

        Returns:
        - None

        Exceptions:
        - Propagates Redis errors on connectivity issues.
        """
        entry = json.dumps(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        key = self._key(session_id)
        await self._client.rpush(key, entry)
        await self._client.ltrim(key, -(self._max_turns * 2), -1)
        if self._ttl:
            await self._client.expire(key, self._ttl)

    async def get_recent_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """
        Return the most recent messages for a session.

        Parameters:
        - session_id: `str`
        - limit: `int | None` max turns to retrieve (defaults to `max_turns`).

        Returns:
        - `list[dict[str, Any]]` parsed message entries with role/content/timestamp.

        Notes:
        - Invalid JSON entries are skipped to avoid breaking retrieval.
        """
        key = self._key(session_id)
        limit = limit or self._max_turns
        raw_entries = await self._client.lrange(key, -(limit * 2), -1)
        messages: list[dict[str, Any]] = []
        for entry in raw_entries:
            try:
                messages.append(json.loads(entry))
            except json.JSONDecodeError:
                continue
        return messages

    async def clear(self, session_id: str) -> None:
        """
        Remove all stored context for a session.

        Parameters:
        - session_id: `str`

        Returns:
        - None
        """
        await self._client.delete(self._key(session_id))
