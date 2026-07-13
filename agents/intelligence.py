"""
Anthropic intelligence layer — generates the relationship brief using Claude.
Called when an account's urgency crosses medium/high/critical threshold.
"""

import json
import logging
import os
from typing import Optional

import anthropic

from utils.helpers import format_messages, format_flags, format_signals

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy client construction — avoids baking in a missing key if this
    module is imported before load_dotenv() has run."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client

BRIEF_SYSTEM_PROMPT = """
You are Pulse, a relationship intelligence agent for B2B customer success teams.
Your job is to analyze signals from a customer's Slack Connect channel and generate
a clear, specific, actionable intelligence brief for the account manager.

You must respond ONLY with valid JSON. No preamble, no markdown, no explanation.

Output schema:
{
  "what_changed": "2-3 sentence description of what specific signals changed and when",
  "why_it_matters": "1-2 sentences on the business risk this represents",
  "champion_status": "healthy | at_risk | silent | departed",
  "champion_summary": "1 sentence on the champion's specific activity pattern",
  "external_context": "1-2 sentences on relevant external signals if any, or null",
  "what_they_might_be_thinking": "1-2 sentences written from the customer's perspective",
  "urgency_reasoning": "1 sentence explaining why this urgency level was assigned",
  "suggested_action": "specific, concrete action the AM should take this week",
  "draft_message": "a ready-to-send Slack message from the AM to the customer champion, 2-3 sentences, warm but purposeful"
}

Be specific. Use actual dates and message counts. Never use generic phrases like
"there may be concerns" — say what the concern is and what evidence points to it.
Write the draft message in first person as the account manager.
"""


def _strip_code_fence(text: str) -> str:
    """Claude sometimes wraps JSON in ```json ... ``` despite instructions not to."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence (may include "json")
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _build_user_prompt(
    account: dict,
    messages: list[dict],
    flagged_messages: list[dict],
    signals: list[dict],
    health_history: list[dict],
    champion_data: dict,
) -> str:
    days_to_renewal = "unknown"
    if account.get("renewal_date"):
        from datetime import datetime
        try:
            renewal = datetime.strptime(account["renewal_date"], "%Y-%m-%d")
            days_to_renewal = str((renewal - datetime.utcnow()).days)
        except ValueError:
            pass

    prev_score = health_history[-8]["score"] if len(health_history) >= 8 else health_history[0]["score"]
    current_score = health_history[-1]["score"]

    if champion_data.get("user_id"):
        champion_block = (
            f"CHAMPION: {champion_data['name']}\n"
            f"- Days since last post: {champion_data['days_silent']}\n"
            f"- Posts this week: {champion_data['posts_this_week']} "
            f"(vs {champion_data['avg_weekly_posts']:.1f} average)\n"
            f"- Colleague reply rate: {champion_data['reply_rate']}%"
        )
    else:
        champion_block = (
            "CHAMPION: tracking not enabled for this account — do not speculate "
            "about champion activity; set champion_status to \"healthy\" and keep "
            "champion_summary to one neutral sentence noting this isn't tracked."
        )

    signals_block = format_signals(signals) if signals else "(external signal monitoring not enabled for this account)"

    return f"""Account: {account['name']}
Contract value: ${account['contract_value']:,}
Days to renewal: {days_to_renewal}
Current health score: {current_score}/100 (was {prev_score}/100 seven days ago)
Urgency: {health_history[-1]['urgency']}

{champion_block}

RECENT MESSAGES (last 30, customer-side only):
{format_messages(messages)}

DETECTED PATTERN FLAGS:
{format_flags(flagged_messages)}

EXTERNAL SIGNALS (last 14 days):
{signals_block}

Generate the intelligence brief now."""


def generate_brief(
    account: dict,
    messages: list[dict],
    flagged_messages: list[dict],
    signals: list[dict],
    health_history: list[dict],
    champion_data: dict,
) -> Optional[dict]:
    """
    Calls Claude to generate a structured intelligence brief.
    Returns parsed dict or None if generation fails.

    If the account has Salesforce CRM lookup enabled, this routes through
    Anthropic's MCP connector so Claude can query the org's live Account
    data (industry, revenue, employee count) mid-request via Salesforce's
    hosted MCP server, and fold it into the brief.
    """
    prompt = _build_user_prompt(
        account, messages, flagged_messages, signals, health_history, champion_data
    )

    if account.get("enable_salesforce_crm"):
        brief = _generate_brief_with_salesforce_mcp(account, prompt)
        if brief:
            return brief
        logger.warning(f"[{account['name']}] Salesforce MCP path failed — falling back to standard brief")

    try:
        response = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=BRIEF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = _strip_code_fence(raw)
        brief = json.loads(raw)
        logger.info(f"[{account['name']}] Brief generated successfully")
        return brief

    except json.JSONDecodeError as e:
        logger.error(f"[{account['name']}] Brief JSON parse error: {e}\nRaw: {raw[:200]}")
        return None
    except anthropic.APIError as e:
        logger.error(f"[{account['name']}] Anthropic API error: {e}")
        return None


def _generate_brief_with_salesforce_mcp(account: dict, prompt: str) -> Optional[dict]:
    """
    Pulse acts as the MCP client here: it spawns Salesforce's official CLI
    MCP server locally (agents.salesforce_mcp.query_account) and queries the
    matching Account record via the real MCP protocol — genuine MCP, genuine
    Salesforce data. The result is folded into the prompt as plain context,
    then a normal Claude call produces the brief.

    (We don't route through Anthropic's server-side MCP connector against
    Salesforce's *hosted* MCP server — that path currently has an open,
    documented bug on Anthropic's side. See agents/salesforce_mcp.py header.)
    """
    from agents.salesforce_mcp import query_account

    record = query_account(account["name"])
    if not record:
        logger.info(f"[{account['name']}] No matching Salesforce Account found via MCP — "
                    f"proceeding without CRM context")
        crm_block = "(No matching Salesforce Account found for this company.)"
    else:
        industry = record.get("Industry") or "unknown"
        revenue = record.get("AnnualRevenue")
        employees = record.get("NumberOfEmployees")
        crm_block = (
            f"Industry: {industry}\n"
            f"Annual Revenue: {'$' + format(revenue, ',.0f') if revenue is not None else 'unknown'}\n"
            f"Employees: {employees if employees is not None else 'unknown'}"
        )
        logger.info(f"[{account['name']}] Salesforce Account matched via MCP: {record.get('Name')}")

    enriched_prompt = (
        f"{prompt}\n\n"
        f"SALESFORCE CRM DATA (queried live via MCP):\n{crm_block}\n\n"
        f"If CRM data is present above, weave relevant context (industry, company "
        f"scale) into why_it_matters or external_context where it strengthens the "
        f"brief. If no CRM data was found, don't mention Salesforce at all."
    )

    try:
        response = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1536,
            system=BRIEF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": enriched_prompt}],
        )
        raw = _strip_code_fence(response.content[0].text.strip())
        brief = json.loads(raw)
        logger.info(f"[{account['name']}] Brief generated with Salesforce MCP context")
        return brief
    except Exception as e:
        logger.error(f"[{account['name']}] Brief generation with Salesforce context failed: {e}")
        return None


def get_champion_data(
    account: dict, messages: list[dict], resolve_name_fn=None
) -> dict:
    """
    Thin wrapper around champion_tracker.get_champion_metrics, kept here for
    backwards compatibility with existing callers (test_brief.py etc).
    Pass resolve_name_fn=lambda uid: client.users_info(user=uid)["user"]["real_name"]
    from main.py to resolve real Slack display names without a circular import.
    """
    from agents.champion_tracker import get_champion_metrics
    return get_champion_metrics(account, messages, resolve_name_fn)


def build_full_brief(account: dict, resolve_name_fn=None) -> Optional[dict]:
    """
    Single entry point that gathers every signal type — internal messages,
    pattern flags, external signals, champion status, health history — and
    produces one unified intelligence brief. This is what the Day 10 alert
    dispatcher calls; it owns fetching its own data so callers don't need to
    know the shape of every underlying query.

    Returns None if there isn't enough health history yet to brief on.
    """
    from db.queries import (
        get_recent_messages, get_flagged_messages,
        get_recent_signals, get_health_history,
    )
    from agents.champion_tracker import get_champion_metrics

    health_history = get_health_history(account["id"])
    if not health_history:
        logger.warning(f"[{account['name']}] No health history yet — skipping brief")
        return None

    messages = get_recent_messages(account["id"], days=30, customer_only=True)
    flagged_messages = get_flagged_messages(account["id"], days=14)

    # Only pull data for features this account has opted into — feeding Claude
    # signals the account owner disabled would make the brief reference things
    # that were deliberately turned off.
    if account.get("enable_external_signals"):
        signals = get_recent_signals(account["id"], days=14)
    else:
        signals = []

    if account.get("enable_champion_tracking"):
        champion_data = get_champion_metrics(account, resolve_name_fn=resolve_name_fn)
    else:
        champion_data = {
            "user_id": None, "name": "Champion tracking not enabled for this account",
            "days_silent": None, "posts_this_week": 0, "avg_weekly_posts": 0,
            "reply_rate": 0, "silence_level": None,
        }

    return generate_brief(
        account, messages, flagged_messages, signals, health_history, champion_data
    )
