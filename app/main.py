"""
FastAPI Application Entrypoint
==============================

Purpose:
- Exposes HTTP endpoints for the customer support agent: `/support` for queries
  and `/health` for service health checks.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies:
- `fastapi` for web framework and exception handling
- `pydantic` for request validation (`SupportRequest`)
- Local agent (`app.agent.EnhancedSupportAgent`)
- Environment: `OPENAI_API_KEY`
"""

import os
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import EnhancedSupportAgent


class SupportRequest(BaseModel):
    """Request model for `/support` endpoint."""

    query: str
    customer_id: str | None = None
    session_id: str | None = None


# Application Setup
app = FastAPI(title="Customer Support Agent")
agent = EnhancedSupportAgent(openai_api_key=os.getenv("OPENAI_API_KEY"))


@app.post("/support")
async def support(request: SupportRequest) -> Dict[str, Any]:
    """
    Handle a support request and return an agent response envelope.

    Parameters:
    - request: `SupportRequest`

    Returns:
    - `Dict[str, Any]`: `{source, response, cached, user_query}`

    Raises:
    - `HTTPException(500)`: On unhandled errors during processing.

    Example:
    ```bash
    curl -X POST http://localhost:8000/support \
      -H 'Content-Type: application/json' \
      -d '{"query": "What are my recent orders?", "customer_id": "123"}'
    ```
    """
    try:
        return await agent.handle_query(request.query, request.customer_id, request.session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Return basic service health information."""
    return {"status": "healthy", "service": "customer-support-agent"}
