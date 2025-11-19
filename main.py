"""
Gradio Entrypoint
=================

Purpose:
- Provide a lightweight chat UI on top of the EnhancedSupportAgent so you can
  interact with the toolbox-backed assistant without running the FastAPI app.

Usage:
- Ensure Postgres/Redis/toolbox are running (see README quick start).
- `uv pip install -r requirements.txt`
- `python main.py` (after sourcing `.env`) to launch the Gradio interface.
"""

import os
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from app.agent import EnhancedSupportAgent


def _load_env() -> None:
    """Load variables from .env if present (supports local runs outside uvicorn)."""
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


def build_agent() -> EnhancedSupportAgent:
    """Instantiate the support agent with env-derived credentials."""
    _load_env()
    return EnhancedSupportAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model_name=os.getenv("AGENT_MODEL"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )


agent = build_agent()


async def handle_message(
    message: str,
    history: list[dict[str, str]],
    customer_id: str | None,
    session_id: str | None,
):
    """Gradio callback that routes the latest user message through the agent."""
    if not message.strip():
        return history, ""

    result = await agent.handle_query(message, customer_id or None, session_id or None)
    reply = result.get("response", "I'm here to help! What else can I assist you with?")
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, ""


def main() -> None:
    """Launch the Gradio interface for interacting with the support agent."""
    with gr.Blocks(title="Customer Support Agent") as demo:
        gr.Markdown(
            """
            ## Customer Support Agent
            Chat with the toolbox-powered assistant. Make sure your data services,
            toolbox server, and `.env` credentials are configured first.
            """
        )

        customer_id = gr.Textbox(label="Customer ID (optional)", placeholder="e.g. 1")
        session_id = gr.Textbox(label="Session ID (optional)", placeholder="Defaults to customer ID")
        chatbot = gr.Chatbot(height=400, type="messages")
        msg = gr.Textbox(label="Message", placeholder="Ask a question...")
        send_btn = gr.Button("Send", variant="primary")
        clear_btn = gr.Button("Clear Conversation")

        send_btn.click(
            handle_message,
            inputs=[msg, chatbot, customer_id, session_id],
            outputs=[chatbot, msg],
        )
        msg.submit(
            handle_message,
            inputs=[msg, chatbot, customer_id, session_id],
            outputs=[chatbot, msg],
        )
        clear_btn.click(lambda: ([], ""), outputs=[chatbot, msg], queue=False)

        demo.queue()

    # Blocking launch; share=False keeps it local.
    demo.launch()


if __name__ == "__main__":
    main()
