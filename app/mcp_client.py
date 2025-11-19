"""
MCP Client
===========

Purpose:
- Thin wrapper around the genai-toolbox server, exposing web search, orders,
  profile, and cache utilities with resilient fallbacks for dev/test.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies:
- `toolbox_core.ToolboxClient` for toolset loading and invocation
- `httpx` for external web search (Tavily API)
- Environment variables: `TOOLBOX_BASE_URL`, `TAVILY_API_KEY`

Security Considerations:
- API keys are read from environment only; never log or expose them.

Performance Considerations:
- HTTP timeouts kept low to avoid hanging requests; local fallbacks ensure responsiveness.

TODO:
- Add retries with exponential backoff for transient toolbox/API failures.
- Implement circuit breaker to avoid hammering failing services.
"""

import os
from typing import Any, Dict, Optional

from toolbox_core import ToolboxClient
import httpx


class MCPClient:
    """
    Thin wrapper around the genai-toolbox server.
    Falls back to in-memory mock data when the toolbox server is unavailable so the
    agent can still function in dev/test environments.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        toolset_name: str = "support-toolset",
    ):
        """
        Initialize the MCP client.

        Parameters:
        - base_url: `str | None` base URL of toolbox server. Defaults to `TOOLBOX_BASE_URL`.
        - toolset_name: `str` name of toolbox toolset to load.

        Returns:
        - None
        """
        self.base_url = base_url or os.getenv("TOOLBOX_BASE_URL", "http://127.0.0.1:5000")
        self.toolset_name = toolset_name
        self._local_cache: Dict[str, str] = {}

    async def _load_tool_map(self) -> Dict[str, Any]:
        """
        Load the toolbox toolset and normalize tool names.

        Returns:
        - `Dict[str, Any]`: Mapping of normalized tool names (dash-separated) to tool callables.

        Notes:
        - Normalization ensures consistent lookup regardless of Python identifier style.
        """
        async with ToolboxClient(self.base_url) as client:
            tools = await client.load_toolset(self.toolset_name)

        tool_map: Dict[str, Any] = {}
        for tool in tools:
            name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
            if name:
                normalized = name.replace("_", "-")
                tool_map[normalized] = tool
        return tool_map

    async def _call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Call a toolbox tool by normalized name.

        Parameters:
        - tool_name: `str` normalized tool key (e.g., `recent-orders`).
        - **kwargs: parameters forwarded to the tool.

        Returns:
        - `Dict[str, Any]`: `{"success": bool, "data"|"error": ...}` envelope.

        Raises:
        - Does not raise; returns `success=False` with `error` message on failure.
        """
        try:
            tool_map = await self._load_tool_map()
            tool = tool_map.get(tool_name)
            if not tool:
                return {"success": False, "error": f"Tool '{tool_name}' not found"}

            result = await tool(**kwargs)
            return {"success": True, "data": result}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    async def web_search(
        self,
        query: str,
        max_results: int | None = None,
        search_depth: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_answer: bool | None = None,
    ) -> Dict[str, Any]:
        """
        Perform a web search using Tavily when available; fallback to mock data.

        Parameters:
        - query: `str`

        Returns:
        - `Dict[str, Any]`: Search result payload with `source` indicating `tavily` or `mock`.

        Security:
        - Uses `TAVILY_API_KEY` from environment; never logs secret values.
        """
        tavily_key = os.getenv("TAVILY_API_KEY")
        if tavily_key:
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    payload: Dict[str, Any] = {"query": query, "api_key": tavily_key}
                    if max_results is not None:
                        payload["max_results"] = max_results
                    if search_depth is not None:
                        payload["search_depth"] = search_depth
                    if include_domains is not None:
                        payload["include_domains"] = include_domains
                    if exclude_domains is not None:
                        payload["exclude_domains"] = exclude_domains
                    if include_answer is not None:
                        payload["include_answer"] = include_answer

                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return {"success": True, "data": data, "source": "tavily"}
            except Exception as exc:  # noqa: BLE001
                return {
                    "success": True,
                    "data": {
                        "query": query,
                        "results": [
                            {
                                "title": f"Mock information about {query}",
                                "snippet": f"This is placeholder data for '{query}'.",
                                "url": "https://example.com",
                            }
                        ],
                    },
                    "source": "mock",
                }

        # Fallback mock data to keep the agent responsive
        return {
            "success": True,
            "data": {
                "query": query,
                "results": [
                    {
                        "title": f"Mock information about {query}",
                        "snippet": f"This is placeholder data for '{query}'.",
                        "url": "https://example.com",
                    }
                ],
            },
            "source": "mock",
        }

    async def fetch_recent_orders(self, customer_id: str) -> Dict[str, Any]:
        """
        Fetch recent orders via toolbox, with mock fallback.

        Parameters:
        - customer_id: `str`

        Returns:
        - `Dict[str, Any]`: Envelope including `success`, `data`, and optionally `source`.
        """
        result = await self._call_tool("recent-orders", customer_id=customer_id)
        if result.get("success"):
            return result

        # Provide a minimal mock result so upstream logic can proceed
        return {
            "success": True,
            "data": [
                {
                    "id": 1,
                    "customer_id": customer_id,
                    "note": "Mock orders (toolbox unavailable)",
                }
            ],
            "source": "mock",
        }

    async def fetch_customer_profile(self, customer_id: str) -> Dict[str, Any]:
        """
        Fetch a customer profile via toolbox, with mock fallback.

        Parameters:
        - customer_id: `str`

        Returns:
        - `Dict[str, Any]`: Envelope including profile data.
        """
        result = await self._call_tool("customer-profile", customer_id=customer_id)
        if result.get("success"):
            return result

        return {
            "success": True,
            "data": [
                {
                    "id": customer_id,
                    "note": "Mock profile (toolbox unavailable)",
                }
            ],
            "source": "mock",
        }

    async def cache_data(self, key: str, value: str, ttl: int = 3600) -> Dict[str, Any]:
        """
        Cache data via toolbox Redis tool; fallback to local memory cache.

        Parameters:
        - key: `str`
        - value: `str`
        - ttl: `int` time-to-live in seconds (default 3600)

        Returns:
        - `Dict[str, Any]`: Success envelope.
        """
        result = await self._call_tool("redis-set-cache", key=key, value=value, ttl=ttl)
        if result.get("success"):
            return result

        # Fallback to in-memory cache
        self._local_cache[key] = value
        return {"success": True, "message": "Cached locally", "storage": "local"}

    async def get_cached_data(self, key: str) -> Dict[str, Any]:
        """
        Retrieve cached data via toolbox; fallback to local memory cache.

        Parameters:
        - key: `str`

        Returns:
        - `Dict[str, Any]`: Envelope with `data` when present.

        Edge Cases:
        - Returns the toolbox envelope (possibly `success=False`) when no local cache exists.
        """
        result = await self._call_tool("redis-get-cache", key=key)
        if result.get("success") and result.get("data") is not None:
            return result

        # Fallback to in-memory cache
        if key in self._local_cache:
            return {"success": True, "data": self._local_cache[key], "storage": "local"}

        return result
