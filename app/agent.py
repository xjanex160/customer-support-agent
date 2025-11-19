"""
Customer Support Agent module
=================================

Purpose:
- Provides `EnhancedSupportAgent`, a customer support agent that routes to toolbox
  tools via an MCP client and generates responses using the Agents SDK.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies:
- `agents` SDK (`agents.Agent`, `Runner`, `function_tool`)
- Model provider (`agents.models.openai_provider.OpenAIProvider`)
- Local toolbox client (`app.mcp_client.MCPClient`)
- Environment variables: `AGENT_MODEL`, `BASE_URL`, `API_KEY`, `OPENAI_API_KEY`

Notes:
- Security: Avoid logging API keys; keys are read from environment and passed only where needed.
- Performance: Tool calls and LLM generation are network-bound; caching is used to reduce repeated work.
- Known Issues: If `BASE_URL` points to a non-OpenAI-compatible endpoint, ensure the provider supports chat completions.
"""

import json
import os
from typing import Any, Dict, List

from agents import Agent as AgentsAgent
from agents import Runner, function_tool
from agents.models.interface import Model
from agents.models.openai_provider import OpenAIProvider

from .mcp_client import MCPClient
from .memory import RedisConversationMemory

# Default to an OpenAI-compatible model; can be overridden via env or ctor.
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "gpt-4o-mini")


class EnhancedSupportAgent:
    """
    Support agent that routes to toolbox tools and generates replies via the
    Agents SDK.

    Purpose:
    - Bridge between user queries and domain tools (orders, profiles, cache, web).
    - Construct LLM prompts and orchestrate tool usage for accurate responses.

Notes:
    - Tools are exposed as functions decorated with `function_tool` to the LLM.
    - The model can be a string (model name) or a custom `Model` instance.

    Example:
    ```python
    agent = EnhancedSupportAgent(openai_api_key=os.getenv("OPENAI_API_KEY"))
    result = await agent.handle_query("What are my recent orders?", customer_id="123")
    print(result["response"])  # human-friendly answer
    ```

    TODO:
    - Add request-level rate limiting to prevent tool abuse.
    - Integrate structured logging (trace IDs) for production debugging.
    - Consider semantic cache keys to reduce hash collision risks.
    """

    def __init__(self, openai_api_key: str | None = None, model_name: str | None = None, base_url: str | None = None):
        """
        Initialize the support agent and underlying clients.

        Parameters:
        - openai_api_key: `str | None`
          API key for OpenAI-compatible providers. Falls back to `API_KEY`/`OPENAI_API_KEY` in env.
        - model_name: `str | None`
          Preferred LLM name. Defaults to `AGENT_MODEL` env or `gpt-4o-mini`.
        - base_url: `str | None`
          Optional custom base URL for OpenAI-compatible providers (e.g., Gemini proxy).

        Returns:
        - None

        Raises:
        - None directly; misconfiguration is handled via fallbacks.
        """
        # === Configuration & Environment ===
        self.mcp_client = MCPClient()
        self.model_name = model_name or DEFAULT_MODEL

        # Allow Google-compatible base_url or alternative providers via env.
        self.base_url = base_url or os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL")
        if self.base_url:
            os.environ.setdefault("BASE_URL", self.base_url)
            os.environ.setdefault("OPENAI_BASE_URL", self.base_url)

        # Track the API key we plan to use (OpenAI or Gemini).
        self.api_key = openai_api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            os.environ.setdefault("API_KEY", openai_api_key)
            os.environ.setdefault("OPENAI_API_KEY", openai_api_key)
        elif self.api_key:
            os.environ.setdefault("API_KEY", self.api_key)
            os.environ.setdefault("OPENAI_API_KEY", self.api_key)

        # Build a custom model when using non-default base URLs; otherwise use model name.
        self._custom_model = self._build_custom_model()

        # === Agent Construction ===
        self.agent = self._build_agent()
        memory_url = os.getenv("MEMORY_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379"
        self.memory = RedisConversationMemory(memory_url)

    def _build_custom_model(self) -> Model | None:
        """
        Build a custom `Model` via `OpenAIProvider` when `base_url` and `api_key` are set.

        Parameters:
        - None

        Returns:
        - `Model | None`: Configured model for custom providers, else `None`.

        Raises:
        - None
        """
        if not self.base_url or not self.api_key:
            return None

        provider = OpenAIProvider(
            api_key=self.api_key,
            base_url=self.base_url,
            use_responses=False,  # Gemini-compatible endpoint only exposes chat completions.
        )
        return provider.get_model(self.model_name)

    def _build_tools(self):
        """
        Define and expose toolbox-backed functions to the LLM.

        Returns:
        - `list[callable]`: Collection of decorated tools available to the agent.

        Notes:
        - Each tool includes input validation and standardized error raising.
        """
        mcp_client = self.mcp_client

        # === Tool Definitions ===
        @function_tool
        async def recent_orders(customer_id: str) -> List[Dict[str, Any]]:
            """
            Fetch the 10 most recent orders for a given customer.

            Parameters:
            - customer_id: `str`
              Identifier of the customer whose orders are requested.

            Returns:
            - `List[Dict[str, Any]]`: List of recent order records.

            Raises:
            - `RuntimeError`: If toolbox call fails or returns an error.
            """
            result = await mcp_client.fetch_recent_orders(customer_id)
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Unknown error"))
            return result.get("data") or []

        @function_tool
        async def customer_profile(customer_id: str) -> Dict[str, Any]:
            """
            Fetch customer profile details for a given customer id.

            Parameters:
            - customer_id: `str`

            Returns:
            - `Dict[str, Any]`: Normalized profile object.

            Raises:
            - `RuntimeError`: If toolbox call fails or returns an error.
            """
            result = await mcp_client.fetch_customer_profile(customer_id)
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Unknown error"))
            data = result.get("data") or {}
            # Toolbox may return a list; normalize to a single dict when applicable.
            if isinstance(data, list) and data:
                return data[0]
            return data

        @function_tool
        async def cached_answer(key: str) -> str:
            """
            Retrieve a cached support answer by key.

            Parameters:
            - key: `str`

            Returns:
            - `str`: Cached value if present.

            Raises:
            - `RuntimeError`: If cache misses or toolbox returns an error.
            """
            result = await mcp_client.get_cached_data(key)
            if result.get("success") and result.get("data") is not None:
                return str(result["data"])
            raise RuntimeError(result.get("error", "Cache miss"))

        @function_tool
        async def web_lookup(
            query: str,
            max_results: int | None = None,
            search_depth: str | None = None,
            include_domains: List[str] | None = None,
            exclude_domains: List[str] | None = None,
            include_answer: bool | None = None,
        ) -> Dict[str, Any]:
            """
            Retrieve web search snippets relevant to a customer question.

            Parameters:
            - query: `str`

            Returns:
            - `Dict[str, Any]`: Search results payload.

            Raises:
            - `RuntimeError`: If toolbox/web search fails.
            """
            result = await mcp_client.web_search(
                query,
                max_results=max_results,
                search_depth=search_depth,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                include_answer=include_answer,
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "Unknown error"))
            return result.get("data") or {}

        return [recent_orders, customer_profile, cached_answer, web_lookup]

    def _build_agent(self) -> AgentsAgent:
        """
        Construct and configure the `AgentsAgent` with instructions, tools, and model.

        Returns:
        - `AgentsAgent`: Configured agent instance ready for `Runner.run`.
        """
        instructions = (
            "You are a helpful, concise customer support agent. "
            "Use the provided tools to fetch customer profile/order data or cached answers. "
            "Always respect the provided customer_id when calling tools. "
            "Cite any key details you used from tools in your reply."
        )

        configured_model: str | Model = self._custom_model or self.model_name

        return AgentsAgent(
            name="SupportAgent",
            instructions=instructions,
            tools=self._build_tools(),
            model=configured_model,
        )

    def _conversation_key(self, customer_id: str | None, session_id: str | None) -> str:
        """Derive a stable key for storing conversation memory."""
        return session_id or customer_id or "anonymous-session"

    def _build_llm_prompt(
        self,
        user_query: str,
        customer_id: str | None,
        memory_entries: List[Dict[str, Any]] | None = None,
    ) -> str:
        """
        Build an LLM prompt that includes customer context and guidance.

        Parameters:
        - user_query: `str`
        - customer_id: `str | None`

        Returns:
        - `str`: Prompt string.
        """
        # === Prompt Building ===
        parts = [
            f"Customer ID: {customer_id or 'unknown'}",
            f"Customer asked: {user_query}",
            "If helpful, call tools to fetch profile, orders, or cached responses before replying.",
        ]
        if memory_entries:
            formatted = "\n".join(
                f"{entry.get('role', 'unknown').title()}: {entry.get('content', '')}" for entry in memory_entries
            )
            parts.append("Recent context:\n" + formatted)
        return "\n".join(parts)

    async def _generate_response(self, user_query: str, customer_id: str | None, session_key: str) -> str:
        """
        Generate a response using the configured agent.

        Parameters:
        - user_query: `str`
        - customer_id: `str | None`

        Returns:
        - `str`: Final response text from the agent or a fallback.

        Exceptions:
        - Swallows runtime exceptions and returns a fallback; consider observing logs in production.

        Performance:
        - Network-bound; consider caching prompts/results when appropriate.
        """
        # Ensure API key exists; otherwise fall back.
        # Performance-sensitive: return quickly when no API key is configured.
        if not (self.api_key or os.getenv("OPENAI_API_KEY")):
            return "I've gathered some information for you. How else can I help?"

        try:
            memory_entries = await self.memory.get_recent_messages(session_key)
        except Exception:
            memory_entries = []
        prompt = self._build_llm_prompt(user_query, customer_id, memory_entries)
        try:
            result = await Runner.run(self.agent, input=prompt)
            return result.final_output or "I'm here to help! What else can I assist you with?"
        except Exception:
            return self._generate_fallback_response({"source": "agent"})

    def _generate_fallback_response(self, context: Dict[str, Any]) -> str:
        """
        Return a friendly, generic response tailored to the context source.

        Parameters:
        - context: `Dict[str, Any]` containing a `source` key.

        Returns:
        - `str`: Safe fallback message.
        """
        source = context.get("source", "unknown")

        responses = {
            "database": "I found your order information. How can I help you with your orders?",
            "web_search": "I've looked up information about your query. What specific aspect would you like to know more about?",
            "cache": "Based on our previous discussions, here's what I can tell you.",
            "agent": "I'll help you with that. Let me know if you need more specific information.",
        }

        return responses.get(source, "I'm here to help! What else can I assist you with?")

    async def handle_query(
        self,
        user_query: str,
        customer_id: str | None = None,
        session_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Public entry point to process a support query.

        Parameters:
        - user_query: `str`
        - customer_id: `str | None` (optional)

        Returns:
        - `Dict[str, Any]`: Response envelope including `source`, `response`, `cached`, and `user_query`.

        Notes:
        - Utilizes a cache-first strategy to avoid repeated generation costs.
        """
        # === Cache-first Orchestration ===
        # Hashing the query keeps keys short; collisions are unlikely but possible.
        session_key = self._conversation_key(customer_id, session_id)
        cache_key = f"support:{customer_id}:{hash(user_query)}" if customer_id else f"support:{hash(user_query)}"

        cached_response = await self.mcp_client.get_cached_data(cache_key)
        if cached_response.get("success") and cached_response.get("data"):
            await self._append_memory(session_key, user_query, cached_response["data"])
            return {
                "source": "cache",
                "response": cached_response["data"],
                "cached": True,
                "user_query": user_query,
            }

        # LLM generation via Agents SDK
        intelligent_response = await self._generate_response(user_query, customer_id, session_key)

        # Cache the final response
        await self.mcp_client.cache_data(cache_key, intelligent_response)
        await self._append_memory(session_key, user_query, intelligent_response)

        return {
            "source": "agent",
            "response": intelligent_response,
            "cached": False,
            "user_query": user_query,
        }

    async def _append_memory(self, session_key: str, user_query: str, response: str) -> None:
        """Persist the latest exchange into Redis-backed memory."""
        try:
            await self.memory.append_message(session_key, "user", user_query)
            await self.memory.append_message(session_key, "assistant", response)
        except Exception:
            # Memory should never break primary response path.
            return
