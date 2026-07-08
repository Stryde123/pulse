"""
RTS (Real-time Search) integration — Slack's assistant.search.context API.

IMPORTANT: RTS searches INSIDE the Slack workspace (messages, files, channels
the app has access to) — it does NOT search external news/web sources. This
powers Pulse's "ask" chatbot feature: an account manager can ask a natural
language question and Pulse searches across every monitored Slack Connect
channel to find relevant context, then has Claude synthesize an answer.

Example: "@Pulse ask what has Brightline said about the CSV bug?"
"""

import logging
from typing import Optional

import anthropic
import os

logger = logging.getLogger(__name__)

RTS_ANSWER_SYSTEM_PROMPT = """
You are Pulse, a relationship intelligence agent. You've been given a set of
Slack messages retrieved via search that are relevant to a question an account
manager asked. Answer the question directly and specifically, citing message
authors and approximate dates where relevant. If the retrieved messages don't
actually answer the question, say so plainly rather than guessing.

Keep the answer to 2-4 sentences. Write in plain text, no markdown formatting,
suitable for a Slack message.
"""


def search_workspace(
    slack_client, query: str, action_token: str, channel_types: Optional[list] = None
) -> list[dict]:
    """
    Calls Slack's Real-time Search API (assistant.search.context) to find
    messages across the workspace relevant to `query`.

    Requires:
    - bot token with search:read.public (or equivalent) scope
    - action_token from the triggering app_mention/message event payload —
      this is short-lived and MUST come from the event that invoked this call.
    """
    channel_types = channel_types or ["public_channel", "private_channel"]

    try:
        response = slack_client.api_call(
            api_method="assistant.search.context",
            json={
                "query": query,
                "action_token": action_token,
                "content_types": ["messages"],
                "channel_types": channel_types,
                "limit": 15,
            },
        )
        if not response.get("ok"):
            logger.error(f"RTS search failed: {response.get('error')}")
            return []
        return response.get("results", {}).get("messages", [])
    except Exception as e:
        logger.error(f"RTS search exception: {e}")
        return []


def answer_question(slack_client, question: str, action_token: str) -> str:
    """
    Full RTS pipeline: search the workspace for relevant context, then have
    Claude synthesize a direct answer.
    """
    results = search_workspace(slack_client, question, action_token)

    if not results:
        return (
            "I couldn't find any relevant messages in the channels I have access to. "
            "Try rephrasing, or make sure I've been added to the right channel."
        )

    context_lines = []
    for r in results:
        author = r.get("author_name", "Unknown")
        channel = r.get("channel_name", "unknown-channel")
        content = r.get("content", "")
        context_lines.append(f"[#{channel}] {author}: {content}")

    context_block = "\n".join(context_lines)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=RTS_ANSWER_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Question: {question}\n\nRetrieved messages:\n{context_block}",
            }],
        )
        return response.content[0].text.strip()
    except anthropic.APIError as e:
        logger.error(f"Answer synthesis failed: {e}")
        return "I found some relevant messages but couldn't synthesize an answer right now."
