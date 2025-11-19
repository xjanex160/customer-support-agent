"""
Integration-style tests for Customer Support Agent
==================================================

Purpose:
- Exercise the `/support` endpoint with representative queries and customer IDs,
  verifying basic success/error flows and caching behavior.

Author: Ebube Imoh
Last Modified: 2025-11-19

Dependencies:
- `httpx.AsyncClient` for async HTTP calls
- Running FastAPI app available at `http://localhost:8000`
"""

import asyncio
import httpx
import json

async def test_agent():
    """
    Exercise the `/support` endpoint with several queries.

    Returns:
    - None; asserts are replaced by printed output for illustrative debugging.

    Notes:
    - In production, replace prints with assertions on response structure/values.
    - Consider parametrizing test cases via `pytest.mark.parametrize`.
    """
    base_url = "http://localhost:8000"
    
    test_cases = [
        {"query": "What are my recent orders?", "customer_id": "1", "session_id": "cust-1"},
        {"query": "How do I use the new dashboard?", "customer_id": "2", "session_id": "cust-2"},
        {"query": "What's my account status?", "customer_id": "1"},
        {"query": "Tell me about product updates", "customer_id": None}
    ]
    
    async with httpx.AsyncClient() as client:
        for test_case in test_cases:
            print(f"\nTesting: {test_case}")
            response = await client.post(
                f"{base_url}/support",
                json=test_case
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success: {result['source']}")
                print(f"Response: {result['response'][:100]}...")
                print(f"Cached: {result.get('cached', False)}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")

if __name__ == "__main__":
    asyncio.run(test_agent())
