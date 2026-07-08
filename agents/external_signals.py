"""
External company signal scanner — supplementary feature, NOT the RTS API.

RTS (Slack's Real-time Search) only searches inside the Slack workspace, so it
cannot see external news. This module fills that gap using Google News RSS
(no API key required) + Claude classification, per the SIGNAL_CLASSIFIER
prompt in the build spec. Runs on a daily APScheduler tick per account.
"""

import logging
import os
import xml.etree.ElementTree as ET
from urllib.parse import quote

import anthropic
import requests

from db.queries import insert_signal, get_recent_signals

logger = logging.getLogger(__name__)

SEARCH_TERMS = ["layoffs", "funding", "CEO departure", "leadership change",
                 "acquisition", "bankruptcy", "hiring freeze"]

SIGNAL_CLASSIFIER_PROMPT = """
Given this news headline and snippet, determine whether it is genuinely about
the specific company "{company}" — our customer — and not a different,
unrelated company or organization that merely shares part of the name (a
common false-positive with generic or common company names).

If the headline is about a different, unrelated entity, set "relevant": false
even if the name matches. Only classify as relevant if you're confident this
is the same company.

Respond ONLY with valid JSON, no markdown:
{{
  "relevant": true or false,
  "signal_type": "layoff | leadership_change | funding | competitor | hiring_freeze | acquisition | negative_pr | other",
  "severity": 1, 2, or 3,
  "summary": "one sentence explaining what happened and why it matters for a vendor relationship"
}}

severity 3 = immediate relationship risk (layoffs, CEO departure, bankruptcy)
severity 2 = near-term risk (hiring freeze, bad earnings, leadership restructure)
severity 1 = monitor situation (minor news, funding that could go either way)

Company we're monitoring: {company}
Headline: {headline}
Snippet: {snippet}
"""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy client construction — avoids baking in a missing key if this
    module is imported before load_dotenv() has run (as happens in main.py,
    where top-of-file imports precede the load_dotenv() call)."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _fetch_news_rss(company: str, term: str) -> list[dict]:
    """Google News RSS search — free, no API key, returns recent headlines."""
    query = quote(f'"{company}" {term}')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item")[:3]:  # top 3 per term
            title = item.findtext("title", "")
            description = item.findtext("description", "")
            link = item.findtext("link", "")
            items.append({"headline": title, "snippet": description, "url": link})
        return items
    except Exception as e:
        logger.warning(f"News fetch failed for '{company} {term}': {e}")
        return []


def _classify(company: str, headline: str, snippet: str) -> dict | None:
    prompt = SIGNAL_CLASSIFIER_PROMPT.format(company=company, headline=headline, snippet=snippet)
    try:
        response = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        import json
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Signal classification failed: {e}")
        return None


def scan_account(account: dict) -> int:
    """
    Scans external news for one account's company name, classifies hits,
    stores relevant ones as signals. Returns count of new signals inserted.

    Deduplicates by article URL (not the classified summary text) — the
    summary is Claude's paraphrase and is worded slightly differently on
    every scan, so comparing against it never matches and lets the same
    article get re-inserted on every run.
    """
    company = account["name"]
    existing = get_recent_signals(account["id"], days=14)
    existing_urls = {s["url"] for s in existing if s.get("url")}

    inserted = 0
    for term in SEARCH_TERMS:
        for item in _fetch_news_rss(company, term):
            if item["url"] in existing_urls:
                continue

            classification = _classify(company, item["headline"], item["snippet"])
            if not classification or not classification.get("relevant"):
                continue

            insert_signal(
                account_id=account["id"],
                signal_type=classification["signal_type"],
                headline=classification["summary"],
                url=item["url"],
                severity=classification["severity"],
            )
            existing_urls.add(item["url"])
            inserted += 1
            logger.info(f"[{company}] New signal: {classification['signal_type']} "
                        f"(sev {classification['severity']}) — {classification['summary']}")

    return inserted


def scan_all_accounts() -> dict:
    from db.queries import get_all_accounts
    results = {}
    for account in get_all_accounts():
        if not account.get("enable_external_signals"):
            continue
        count = scan_account(account)
        results[account["name"]] = count
    return results
