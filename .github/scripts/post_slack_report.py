#!/usr/bin/env python3
import json
import os
import sys
import requests

with open("reports/latest.json") as f:
    data = json.load(f)

actionable = data.get("actionable", [])
cold = data.get("cold_emails", [])
date_str = data.get("date_str", "")
time_str = data.get("time_str", "")

lines = [f"<@U059A6VD65T> *Inbox Report — {date_str} ({time_str})*\n"]
lines.append("*Actionable Emails*\n")
if actionable:
    for i, item in enumerate(actionable, 1):
        lines.append(f"{i}. *{item['subject']}* | {item['from_email']} | {item['action_needed']}")
else:
    lines.append("_No actionable emails._")

lines.append(f"\n---\n\n*Cold Email Count: {len(cold)}*")
if cold:
    lines.append(", ".join(f"{c['from_email']} ({c['pitch_summary']})" for c in cold))

lines.append("\n---")
lines.append("_Reports run at 7 AM & 3 PM ET, Mon–Fri_")

message = "\n".join(lines)

token = os.environ["SLACK_BOT_TOKEN"]
r = requests.post(
    "https://slack.com/api/chat.postMessage",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json={"channel": "C0B16N4MDRQ", "text": message},
)

print(f"Status: {r.status_code}")
print(f"Response: {r.text}")

result = r.json()
if result.get("ok"):
    print("Posted to Slack successfully.")
else:
    print(f"Slack error: {result.get('error')}")
    sys.exit(1)
