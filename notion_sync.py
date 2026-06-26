"""Push a run summary row into a Notion database (optional, best-effort).

Reads NOTION_TOKEN + NOTION_DATABASE_ID from the environment. If either is
missing it skips silently with exit 0, so the bot runs fine without Notion.
Notion is a human-readable dashboard only -- ledger.json is the source of truth,
never this.

Set up (one time):
  1. Create a Notion internal integration -> copy the secret -> GitHub repo
     Settings > Secrets and variables > Actions > New secret: NOTION_TOKEN.
  2. Create a Notion database with these properties (exact names/types):
       Name (Title), Equity (Number), Return % (Number),
       Open (Number), Closed (Number), Strategy (Text)
  3. Share that database page with your integration (••• > Connections).
  4. Copy the database id from its URL -> secret: NOTION_DATABASE_ID.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.getenv("NOTION_TOKEN")
DB_ID = os.getenv("NOTION_DATABASE_ID")
LEDGER_PATH = os.getenv("LEDGER_PATH", "ledger.json")
STRATEGY = os.getenv("STRATEGY", "macd_crossover")


def main():
    if not TOKEN or not DB_ID:
        print("notion_sync: NOTION_TOKEN/NOTION_DATABASE_ID not set -> skip")
        return 0
    if not os.path.exists(LEDGER_PATH):
        print("notion_sync: no ledger.json yet -> skip")
        return 0

    with open(LEDGER_PATH) as f:
        led = json.load(f)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "parent": {"database_id": DB_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": stamp}}]},
            "Equity": {"number": round(led.get("equity", led.get("cash", 0.0)), 2)},
            "Return %": {"number": led.get("total_return_pct", 0.0)},
            "Open": {"number": len(led.get("positions", {}))},
            "Closed": {"number": len(led.get("history", []))},
            "Strategy": {"rich_text": [{"text": {"content": STRATEGY}}]},
        },
    }

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"notion_sync: pushed row ({r.status})")
        return 0
    except urllib.error.HTTPError as e:
        # Don't fail the whole run just because Notion rejected the row.
        print(f"notion_sync: HTTP {e.code} {e.read().decode()[:300]}")
        return 0
    except Exception as e:
        print(f"notion_sync: {type(e).__name__} {e}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
