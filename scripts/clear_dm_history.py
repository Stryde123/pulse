"""
One-off cleanup: deletes every message Pulse (the bot) has posted in its
direct-message channel(s), so the DM looks fresh for a demo recording.

Limitation: the bot token can only delete messages the bot itself authored
(Slack's chat.delete permission model) — it cannot delete the human side of
the conversation. Delete your own messages manually in the Slack UI
(hover -> More actions -> Delete message) after running this.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])


def get_bot_user_id() -> str:
    return client.auth_test()["user_id"]


def get_dm_channels() -> list:
    channels = []
    cursor = None
    while True:
        resp = client.conversations_list(types="im", limit=200, cursor=cursor)
        channels.extend(resp["channels"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def clear_bot_messages(channel_id: str, bot_user_id: str) -> int:
    deleted = 0
    cursor = None
    while True:
        resp = client.conversations_history(channel=channel_id, limit=200, cursor=cursor)
        for msg in resp["messages"]:
            if msg.get("user") == bot_user_id or msg.get("bot_id"):
                try:
                    client.chat_delete(channel=channel_id, ts=msg["ts"])
                    deleted += 1
                    time.sleep(0.3)  # stay well under Slack's rate limits
                except SlackApiError as e:
                    print(f"  ! Failed to delete {msg['ts']}: {e.response['error']}")
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return deleted


def main():
    bot_user_id = get_bot_user_id()
    print(f"Bot user ID: {bot_user_id}")

    channels = get_dm_channels()
    print(f"Found {len(channels)} DM channel(s).")

    total_deleted = 0
    for ch in channels:
        channel_id = ch["id"]
        print(f"\nClearing bot messages in {channel_id}...")
        count = clear_bot_messages(channel_id, bot_user_id)
        print(f"  Deleted {count} message(s).")
        total_deleted += count

    print(f"\nDone. Deleted {total_deleted} bot message(s) total.")
    print("Delete your own messages manually in Slack (hover -> More actions -> "
          "Delete message) to fully clear the thread.")


if __name__ == "__main__":
    main()
