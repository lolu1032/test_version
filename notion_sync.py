"""Push this run's trade events into a Notion database (optional, best-effort).

Writes ONE row per trade event from the latest scan: every BUY (with symbol,
entry price, stop-loss, take-profit) and every SELL (with reason, PnL, and the
cash left to roll into the next trade). If there were no events this run, it
writes nothing. Reads NOTION_TOKEN + NOTION_DATABASE_ID from the environment;
skips silently (exit 0) if unset.

ledger.json is the source of truth -- Notion is just a human-readable log.

Database columns expected (created/updated by setup):
  Name (Title), Action (Text), Symbol (Text), Price (Number),
  Stop Loss (Number), Take Profit (Number), Reason (Text),
  PnL (Number), Cash After (Number), Equity (Number)
"""

import json
import os
import urllib.request
import urllib.error

TOKEN = os.getenv("NOTION_TOKEN")
DB_ID = os.getenv("NOTION_DATABASE_ID")
LEDGER_PATH = os.getenv("LEDGER_PATH", "ledger.json")


def _title(ev):
    ts = ev.get("ts", "")[:16].replace("T", " ")
    return f"{ts} {ev.get('action','')} {ev.get('symbol','')}"


def _num(props, name, value):
    if value is not None:
        props[name] = {"number": round(float(value), 6)}


def _text(props, name, value):
    if value is not None:
        props[name] = {"rich_text": [{"text": {"content": str(value)}}]}


def _post(payload):
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
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def main():
    if not TOKEN or not DB_ID:
        print("notion_sync: NOTION_TOKEN/NOTION_DATABASE_ID not set -> skip")
        return 0
    if not os.path.exists(LEDGER_PATH):
        print("notion_sync: no ledger.json yet -> skip")
        return 0

    with open(LEDGER_PATH) as f:
        led = json.load(f)

    events = led.get("last_run_events", [])
    if not events:
        print("notion_sync: no trade events this run -> nothing to push")
        return 0

    pushed = 0
    for ev in events:
        props = {"Name": {"title": [{"text": {"content": _title(ev)}}]}}
        _text(props, "Action", ev.get("action"))
        _text(props, "Symbol", ev.get("symbol"))
        _num(props, "Price", ev.get("price"))
        _num(props, "Stop Loss", ev.get("stop_loss"))
        _num(props, "Take Profit", ev.get("take_profit"))
        _text(props, "Reason", ev.get("reason"))
        _num(props, "PnL", ev.get("pnl"))
        _num(props, "Cash After", ev.get("cash_after"))
        _num(props, "Equity", ev.get("equity"))
        try:
            _post({"parent": {"database_id": DB_ID}, "properties": props})
            pushed += 1
        except urllib.error.HTTPError as e:
            print(f"notion_sync: HTTP {e.code} {e.read().decode()[:300]}")
        except Exception as e:
            print(f"notion_sync: {type(e).__name__} {e}")

    print(f"notion_sync: pushed {pushed}/{len(events)} event rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
