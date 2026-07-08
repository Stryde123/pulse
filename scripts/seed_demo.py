"""
Seed the three demo accounts and pre-load message history for the hackathon demo.

Usage:
    python scripts/seed_demo.py

Set real channel IDs and user IDs via env vars or edit the ACCOUNTS block below.
Run AFTER creating the channels in your Slack sandbox and noting their IDs.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db.schema import init_db
from db.queries import (
    insert_account, get_account_by_channel,
    insert_message, insert_health_score, insert_signal,
)

# ---------------------------------------------------------------------------
# Edit these once you have real Slack channel + user IDs from your sandbox
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {
        "name": "Acme Corp",
        "channel_id": os.getenv("ACME_CHANNEL_ID", "C_ACME"),
        "am_user_id": os.getenv("AM_USER_ID", "U_AM001"),
        "champion_user_id": os.getenv("ACME_CHAMPION_ID", "U_ACME_CHAMP"),
        "contract_value": 85000,
        "renewal_date": "2027-01-15",
    },
    {
        "name": "Brightline SaaS",
        "channel_id": os.getenv("BRIGHTLINE_CHANNEL_ID", "C_BRIGHTLINE"),
        "am_user_id": os.getenv("AM_USER_ID", "U_AM001"),
        "champion_user_id": os.getenv("BRIGHTLINE_CHAMPION_ID", "U_JENNIFER"),
        "contract_value": 120000,
        "renewal_date": "2026-12-01",
    },
    {
        "name": "Vortex Inc",
        "channel_id": os.getenv("VORTEX_CHANNEL_ID", "C_VORTEX"),
        "am_user_id": os.getenv("AM_USER_ID", "U_AM001"),
        "champion_user_id": os.getenv("VORTEX_CHAMPION_ID", "U_VORTEX_CHAMP"),
        "contract_value": 210000,
        "renewal_date": "2026-09-30",
    },
]

# ---------------------------------------------------------------------------
# Message histories — times are relative offsets in days ago
# ---------------------------------------------------------------------------

def days_ago(n: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return str(dt.timestamp())


ACME_MESSAGES = [
    # Healthy — regular cadence, positive
    (days_ago(30), "U_ACME_CHAMP", True,  "Hey team, loving the new dashboard features!"),
    (days_ago(29), "U_AM001",      False, "Glad to hear it! Let us know if you need anything."),
    (days_ago(27), "U_ACME_CHAMP", True,  "Quick question on the API rate limits — we're scaling up usage."),
    (days_ago(27), "U_AM001",      False, "Of course, I'll get you the enterprise limits doc."),
    (days_ago(25), "U_ACME_CHAMP", True,  "Perfect, our devs are super happy with the integration."),
    (days_ago(22), "U_ACME_CHAMP", True,  "Can we schedule our quarterly review for next week?"),
    (days_ago(22), "U_AM001",      False, "Absolutely, sending a calendar invite now."),
    (days_ago(20), "U_ACME_CHAMP", True,  "Great call today! The roadmap looks really promising."),
    (days_ago(18), "U_ACME_CHAMP", True,  "We onboarded 3 more team members this week, going really well."),
    (days_ago(18), "U_AM001",      False, "That's fantastic, let me know if they need any training resources."),
    (days_ago(15), "U_ACME_CHAMP", True,  "The new export feature saved us hours this week, thank you!"),
    (days_ago(12), "U_ACME_CHAMP", True,  "Any update on the SSO integration timeline?"),
    (days_ago(12), "U_AM001",      False, "SSO is scheduled for Q3, I'll keep you posted on the beta."),
    (days_ago(10), "U_ACME_CHAMP", True,  "Sounds good! We're really happy with the product and support."),
    (days_ago(7),  "U_ACME_CHAMP", True,  "Hope you have a great weekend! Talk next week."),
    (days_ago(5),  "U_AM001",      False, "Thanks! Any questions before your team demo on Thursday?"),
    (days_ago(4),  "U_ACME_CHAMP", True,  "Nope, we're all set. Really looking forward to it."),
    (days_ago(2),  "U_ACME_CHAMP", True,  "Demo went great! The VP was impressed. Full rollout approved."),
    (days_ago(2),  "U_AM001",      False, "Amazing news! Let's set up the implementation call."),
    (days_ago(1),  "U_ACME_CHAMP", True,  "Calendar invite sent. This is going to be a great partnership."),
]

BRIGHTLINE_MESSAGES = [
    # Starts healthy, declines — HERO DEMO ACCOUNT
    (days_ago(30), "U_JENNIFER",   True,  "Hi! Really excited to get started with the platform."),
    (days_ago(30), "U_AM001",      False, "Welcome! We're thrilled to have Brightline on board."),
    (days_ago(28), "U_JENNIFER",   True,  "The onboarding docs are really clear, this is going smoothly."),
    (days_ago(26), "U_JENNIFER",   True,  "Quick question on the reporting module — can we filter by region?"),
    (days_ago(26), "U_AM001",      False, "Yes! I'll record a quick walkthrough for you."),
    (days_ago(24), "U_JENNIFER",   True,  "Perfect, our team loved the walkthrough. Thanks for the quick turnaround."),
    (days_ago(21), "U_JENNIFER",   True,  "We're planning to expand usage to the sales team next month."),
    (days_ago(21), "U_AM001",      False, "Great! I'll prepare a sales team onboarding kit."),
    (days_ago(18), "U_JENNIFER",   True,  "The sales kit looks good. One thing — the CSV import is a bit slow."),
    (days_ago(18), "U_AM001",      False, "Noted, I've filed a ticket with the product team."),
    # Tone starts shifting ~2 weeks ago
    (days_ago(14), "U_JENNIFER",   True,  "Just following up on the CSV import issue — still waiting on an update."),
    (days_ago(13), "U_AM001",      False, "Sorry for the delay, I'll chase the eng team today."),
    (days_ago(11), "U_JENNIFER",   True,  "Our team has been discussing the platform performance during peak hours."),
    (days_ago(10), "U_AM001",      False, "Understood, let me pull the performance logs and get back to you."),
    # Champion goes quiet — last post 9 days ago
    (days_ago(9),  "U_JENNIFER",   True,  "Still waiting on the implementation timeline and the CSV fix. "
                                          "We've reached out last week with no response on the ticket."),
    # 9 days of silence from Jennifer after this
    (days_ago(7),  "U_AM001",      False, "Hi Jennifer, just checking in — any questions I can help with?"),
    # No reply
]

VORTEX_MESSAGES = [
    # Critical — champion (Marcus) goes silent at day 13; procurement takes over with hostile signals
    (days_ago(30), "U_VORTEX_CHAMP", True,  "Hi, excited to kick things off."),
    (days_ago(28), "U_AM001",         False, "Welcome! Big things ahead for the partnership."),
    (days_ago(25), "U_VORTEX_CHAMP", True,  "We're ramping up the team, need 5 more licences."),
    (days_ago(24), "U_AM001",         False, "On it, licences added — let me know if you need more."),
    (days_ago(20), "U_VORTEX_CHAMP", True,  "Leadership wants to revisit the contract scope after Q2 review."),
    (days_ago(19), "U_AM001",         False, "Happy to discuss — I'll set up a call with our CS team."),
    (days_ago(16), "U_VORTEX_CHAMP", True,  "We've been talking internally about platform consolidation across the org."),
    (days_ago(15), "U_VORTEX_CHAMP", True,  "We're also looking at alternatives to streamline our stack."),
    # Champion (Marcus) goes silent from day 13 onward — procurement rep takes over
    (days_ago(10), "U_VORTEX_PROC",  True,  "Hi, I'm Sarah from procurement. Can you send over the contract terms and cancellation policy?"),
    (days_ago(10), "U_AM001",         False, "Of course Sarah, sending now. Is everything okay with the account?"),
    (days_ago(8),  "U_VORTEX_PROC",  True,  "How do we export our data if we decide to make a change?"),
    (days_ago(6),  "U_VORTEX_PROC",  True,  "Per my last email, we need the data export documentation ASAP."),
    (days_ago(4),  "U_AM001",         False, "Sending the docs now — I'd love to set up a call to address any concerns directly."),
    (days_ago(3),  "U_VORTEX_PROC",  True,  "We'll circle back after our internal review. Not a priority right now."),
    (days_ago(1),  "U_VORTEX_PROC",  True,  "Evaluating other options — please send the final contract termination terms."),
]

HEALTH_HISTORIES = {
    "Acme Corp": [
        (30, 95, "low"), (25, 93, "low"), (20, 97, "low"),
        (15, 94, "low"), (10, 96, "low"), (5, 98, "low"), (0, 95, "low"),
    ],
    "Brightline SaaS": [
        (30, 91, "low"), (25, 88, "low"), (20, 82, "low"),
        (15, 74, "low"), (10, 63, "medium"), (5, 54, "medium"), (0, 44, "high"),
    ],
    "Vortex Inc": [
        (30, 88, "low"), (25, 75, "low"), (20, 60, "medium"),
        (15, 45, "high"), (10, 32, "high"), (5, 18, "critical"), (0, 12, "critical"),
    ],
}

SIGNALS = {
    "Brightline SaaS": [
        ("layoff", "Brightline SaaS announces 15% workforce reduction amid market slowdown", None, 3),
    ],
    "Vortex Inc": [
        ("leadership_change", "Vortex Inc CEO Marcus Webb steps down, CFO named interim", None, 3),
        ("hiring_freeze",     "Vortex Inc pauses all external hiring through Q3", None, 2),
    ],
}


def seed():
    init_db()
    print("Seeding demo data...\n")

    account_ids = {}

    for spec in ACCOUNTS:
        existing = get_account_by_channel(spec["channel_id"])
        if existing:
            print(f"  Account '{spec['name']}' already exists (id={existing['id']}), skipping insert.")
            account_ids[spec["name"]] = existing["id"]
            continue

        aid = insert_account(
            name=spec["name"],
            channel_id=spec["channel_id"],
            am_user_id=spec["am_user_id"],
            champion_user_id=spec["champion_user_id"],
            contract_value=spec["contract_value"],
            renewal_date=spec["renewal_date"],
            enable_champion_tracking=True,
            enable_external_signals=True,
            enable_salesforce_crm=True,
        )
        account_ids[spec["name"]] = aid
        print(f"  + Account '{spec['name']}' ->id={aid}")

    messages_map = {
        "Acme Corp": (ACME_MESSAGES, os.getenv("AM_USER_ID", "U_AM001")),
        "Brightline SaaS": (BRIGHTLINE_MESSAGES, os.getenv("AM_USER_ID", "U_AM001")),
        "Vortex Inc": (VORTEX_MESSAGES, os.getenv("AM_USER_ID", "U_AM001")),
    }

    for acct_name, (msgs, am_id) in messages_map.items():
        aid = account_ids[acct_name]
        channel_id = next(a["channel_id"] for a in ACCOUNTS if a["name"] == acct_name)
        for ts, user_id, is_customer, text in msgs:
            insert_message(aid, channel_id, user_id, text, is_customer, ts)
        print(f"  + {len(msgs)} messages seeded for '{acct_name}'")

    for acct_name, history in HEALTH_HISTORIES.items():
        aid = account_ids[acct_name]
        for days_back, score, urgency in history:
            insert_health_score(aid, score, urgency)
        print(f"  + Health history seeded for '{acct_name}'")

    for acct_name, sigs in SIGNALS.items():
        aid = account_ids[acct_name]
        for sig_type, headline, url, severity in sigs:
            insert_signal(aid, sig_type, headline, url, severity)
        print(f"  + {len(sigs)} signal(s) seeded for '{acct_name}'")

    print("\nSeed complete.")
    for name, aid in account_ids.items():
        print(f"  {name}: account_id={aid}")


if __name__ == "__main__":
    seed()
