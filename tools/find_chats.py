"""List the chats/channels the bot has seen, so we can fill TELEGRAM_CHANNEL_ID / TELEGRAM_ADMIN_CHAT_ID in .env.

Prints chat ids and titles only; the bot token is never printed.
"""
import os
import sys

import requests

sys.path.insert(0, ".")
from sthlm.cli import load_env

load_env()
token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    sys.exit("TELEGRAM_BOT_TOKEN is empty in .env")

me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
if not me.get("ok"):
    sys.exit(f"Token rejected by Telegram: {me.get('description')}")
print("Bot OK: @" + me["result"]["username"])

upd = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
seen = {}
topics = {}
for u in upd.get("result", []):
    for key in ("message", "channel_post", "my_chat_member", "edited_channel_post"):
        msg = u.get(key) or {}
        c = msg.get("chat")
        if c:
            seen[c["id"]] = (c.get("type"), c.get("title") or c.get("first_name") or c.get("username"))
            if msg.get("message_thread_id"):      # forum topic: the thread id identifies it
                name = (msg.get("reply_to_message") or {}).get("forum_topic_created", {}).get("name") or ""
                topics.setdefault((c["id"], msg["message_thread_id"]), name)
if not seen:
    print("No chats seen yet. Post a message in the channel and send /start to the bot, then run again.")
for cid, (typ, name) in seen.items():
    print(f"{typ:<10} id={cid}  name={name}")
for (cid, tid), name in topics.items():
    print(f"  topic thread_id={tid} in chat {cid} {name}")
