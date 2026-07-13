"""
Salesforce MCP integration — Pulse acts as a genuine MCP client, spawning the
official Salesforce CLI MCP server (@salesforce/mcp, run via npx) over stdio
and calling its run_soql_query tool to pull live Account data.

We deliberately do NOT use Anthropic's server-side MCP connector (passing
mcp_servers to the Messages API against Salesforce's *hosted* MCP server) —
that path has a currently open, documented bug on Anthropic's side
(github.com/anthropics/claude-ai-mcp, multiple issues, "Authorization with
the MCP server failed" even through the official OAuth flow). Running the
official server locally and speaking MCP to it ourselves sidesteps that
entirely while still using the real protocol and real Salesforce data.

Requires:
  - Node.js + npm (npx @salesforce/mcp)
  - Salesforce CLI authenticated locally: `sf org login web --alias pulse-org`
"""

import asyncio
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

SF_ORG_ALIAS = os.environ.get("SALESFORCE_ORG_ALIAS", "pulse-org")
SF_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _query_account_async(company_name: str) -> Optional[dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command="npx",
        # Pinned to a known-working version — later releases pull an undici
        # version that requires webidl APIs not present in Node 20, causing
        # "webidl.util.markAsUncloneable is not a function" on this host.
        args=["-y", "@salesforce/mcp@0.30.14", "--orgs", SF_ORG_ALIAS, "--toolsets", "data"],
    )

    # Escape single quotes defensively — company names go straight into SOQL
    safe_name = company_name.replace("'", "\\'")
    query = f"SELECT Id, Name, Industry, AnnualRevenue, NumberOfEmployees FROM Account WHERE Name = '{safe_name}' LIMIT 1"

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "run_soql_query",
                arguments={
                    "query": query,
                    "usernameOrAlias": SF_ORG_ALIAS,
                    "directory": SF_PROJECT_DIR,
                },
            )

            if getattr(result, "isError", False):
                raw_text = "; ".join(b.text for b in result.content if hasattr(b, "text"))
                logger.error(f"Salesforce MCP tool returned an error for '{company_name}': {raw_text}")
                return None

            import json
            for block in result.content:
                if not hasattr(block, "text"):
                    continue

                # The tool prefixes its JSON payload with a human-readable
                # line like "SOQL query results:\n\n{...}" — strip everything
                # before the first '{' so json.loads gets a clean object.
                text = block.text
                brace_idx = text.find("{")
                if brace_idx == -1:
                    logger.warning(f"Salesforce MCP result had no JSON object for '{company_name}': "
                                    f"{text[:300]}")
                    continue

                try:
                    data = json.loads(text[brace_idx:])
                    records = data.get("records", [])
                    if records:
                        return records[0]
                    logger.info(f"Salesforce query for '{company_name}' returned 0 records "
                                f"(query ran fine, no match)")
                except json.JSONDecodeError as e:
                    logger.warning(f"Salesforce MCP JSON parse failed for '{company_name}': {e} — "
                                    f"raw: {text[:300]}")
                    continue
            return None


def _flatten_exception_group(eg: BaseExceptionGroup) -> list:
    """Exception groups can nest arbitrarily deep — recurse to find the
    actual leaf exceptions instead of printing an opaque group repr."""
    leaves = []
    for sub in eg.exceptions:
        if isinstance(sub, BaseExceptionGroup):
            leaves.extend(_flatten_exception_group(sub))
        else:
            leaves.append(sub)
    return leaves


def query_account(company_name: str, timeout: float = 45.0) -> Optional[dict]:
    """
    Synchronous wrapper — spawns the Salesforce MCP server, queries for an
    Account matching company_name, and returns the record dict (or None if
    not found / any error occurs). Safe to call from sync code like the
    brief generator; swallows errors so a Salesforce hiccup never blocks
    brief generation.
    """
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        return asyncio.run(asyncio.wait_for(_query_account_async(company_name), timeout=timeout))
    except asyncio.TimeoutError:
        logger.error(f"Salesforce MCP query timed out for '{company_name}'")
        return None
    except BaseExceptionGroup as eg:
        for sub in _flatten_exception_group(eg):
            logger.error(f"Salesforce MCP query sub-exception for '{company_name}': "
                         f"{type(sub).__name__}: {sub}")
        return None
    except Exception as e:
        logger.error(f"Salesforce MCP query failed for '{company_name}': {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Write-back: log an Activity Task on the matched Account when Pulse fires
# an alert. This is deliberately a direct REST call (not routed through the
# MCP server) — @salesforce/mcp's 'data' toolset only exposes run_soql_query
# (read) in this GA release, no write tool. The read path stays genuinely
# MCP-client-driven; write-back reuses the OAuth Client Credentials setup
# already proven working for org queries, so Salesforce is a two-way system
# rather than a lookup Pulse never writes back to.
# ---------------------------------------------------------------------------

_oauth_cache: dict = {"access_token": None, "instance_url": None, "expires_at": 0}


def _get_rest_credentials() -> Optional[tuple]:
    import time
    import requests

    now = time.time()
    if _oauth_cache["access_token"] and now < _oauth_cache["expires_at"]:
        return _oauth_cache["access_token"], _oauth_cache["instance_url"]

    domain = os.environ.get("SALESFORCE_DOMAIN")
    client_id = os.environ.get("SALESFORCE_CLIENT_ID")
    client_secret = os.environ.get("SALESFORCE_CLIENT_SECRET")
    if not all([domain, client_id, client_secret]):
        return None

    try:
        resp = requests.post(
            f"https://{domain}/services/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _oauth_cache["access_token"] = data["access_token"]
        _oauth_cache["instance_url"] = data["instance_url"]
        _oauth_cache["expires_at"] = now + (15 * 60) - 60
        return _oauth_cache["access_token"], _oauth_cache["instance_url"]
    except Exception as e:
        logger.error(f"Salesforce REST auth failed: {e}")
        return None


def log_activity(account_id: str, subject: str, description: str) -> bool:
    """
    Creates a Task on the given Account Id summarizing a Pulse alert —
    makes the Salesforce Account a real activity record of what Pulse
    detected, not just a read-only data source.
    """
    import requests

    creds = _get_rest_credentials()
    if not creds:
        logger.warning("Salesforce credentials unavailable — skipping activity write-back")
        return False
    access_token, instance_url = creds

    try:
        resp = requests.post(
            f"{instance_url}/services/data/v60.0/sobjects/Task",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={
                "WhatId": account_id,
                "Subject": subject,
                "Description": description[:32000],  # Salesforce long-text-area cap
                "Status": "Completed",
                "ActivityDate": __import__("datetime").date.today().isoformat(),
            },
            timeout=15,
        )
        if resp.status_code == 201:
            logger.info(f"Logged Pulse alert activity on Salesforce Account {account_id}")
            return True
        logger.error(f"Salesforce Task creation failed ({resp.status_code}): {resp.text[:300]}")
        return False
    except Exception as e:
        logger.error(f"Salesforce Task creation exception: {e}")
        return False
