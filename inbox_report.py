#!/usr/bin/env python3
"""
Inbox Report — scans Gmail for actionable emails and cold emails,
posts a formatted summary to Slack.
"""

import os
import json
import datetime
import pytz
from pathlib import Path
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import anthropic
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
SLACK_BOT_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID   = "C0B16N4MDRQ"
SLACK_MENTION_USER = "U059A6VD65T"

GMAIL_SCOPES         = ["https://www.googleapis.com/auth/gmail.readonly"]
GOOGLE_CREDS_FILE    = BASE_DIR / "google_credentials.json"
GOOGLE_TOKEN_FILE    = BASE_DIR / "google_token.json"

GMAIL_QUERY = (
    "to:max@wellcopy.net newer_than:14d "
    "-from:notifications@figma.com -from:noreply@figma.com "
    "-from:zapier.com -from:make.com -from:close.com "
    "-from:mercury.com -from:wistia.com -from:fathom.video "
    "-from:google.com -from:googleusercontent.com "
    "-from:meta.com -from:facebook.com "
    "-from:notification@slack.com -from:no-reply@slack.com "
    "-from:notifications@calendly.com -from:noreply@github.com "
    "-from:noreply@smartsuite.com -from:mailer@shopify.com "
    "-from:osos-corps@sos.wa.gov -from:no-reply@klaviyo.com"
)

EXCLUSION_RULES = """
EXCLUDE these email types — do not include them in either list:
- Figma seat requests, Zapier/Make/Close CRM errors or tasks
- Mercury feedback, Wistia limits, Fathom consent
- Google Drive shares, bounce-backs / delivery failures
- Security alerts, 2FA / verification codes
- Meta / Facebook partner or pixel notifications
- Calendar accepts, declines, or automated Calendly confirmations
- Newsletters, marketing emails, product update digests
- Receipts, invoices, subscription renewal reminders
- Automated platform notifications (Slack digest emails, GitHub token alerts, Notion updates, SmartSuite automations)
- Internal team calendar invites (from @wellcopy.net senders)
- Time-off requests or internal approvals
- Supercut.ai "first view" notifications
- beehiiv / Gumroad newsletter digests

ACTIONABLE — include only direct human conversations where someone outside Well Copy
is actively waiting on Max to respond:
- Active sales conversations (audit delivered, prospect replied, waiting on next steps)
- Partnership introductions where Max has not yet followed up with the other party
- Inbound lead or collab proposals requiring a decision
- Client escalations or issues requiring Max's input
- Job applicants following up on open positions

COLD EMAILS — unsolicited outreach from unknown senders pitching:
- Tools, software, SaaS products
- Freelance/agency talent or staffing
- Lead generation or ad credits
- Paid collaborations or sponsorships
- Any pitch where the sender has no prior relationship with Max
"""

# ── Gmail ─────────────────────────────────────────────────────────────────────

def get_gmail_service():
    creds = None
    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_FILE), GMAIL_SCOPES)
            auth_url, _ = flow.authorization_url(prompt="consent")
            print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")
            code = input("Paste the authorization code here: ")
            flow.fetch_token(code=code)
            creds = flow.credentials
        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def fetch_threads(service, max_pages=3):
    threads = []
    page_token = None
    for _ in range(max_pages):
        params = {"userId": "me", "q": GMAIL_QUERY, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        result = service.users().threads().list(**params).execute()
        batch = result.get("threads", [])
        # Fetch snippet + metadata for each thread
        for t in batch:
            detail = service.users().threads().get(
                userId="me", id=t["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"]
            ).execute()
            messages = detail.get("messages", [])
            if not messages:
                continue
            last_msg = messages[-1]
            headers = {h["name"]: h["value"] for h in last_msg.get("payload", {}).get("headers", [])}
            threads.append({
                "subject":  headers.get("Subject", "(no subject)"),
                "from":     headers.get("From", ""),
                "snippet":  last_msg.get("snippet", ""),
                "date":     headers.get("Date", ""),
                "msg_count": len(messages),
            })
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return threads


# ── Claude categorisation ─────────────────────────────────────────────────────

def categorise_emails(threads):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    email_list = "\n".join(
        f"{i+1}. FROM: {t['from']} | SUBJECT: {t['subject']} | "
        f"DATE: {t['date']} | SNIPPET: {t['snippet'][:200]}"
        for i, t in enumerate(threads)
    )

    prompt = f"""You are an executive assistant filtering emails for Max Sturtevant, founder of Well Copy (an email/SMS marketing agency).

{EXCLUSION_RULES}

Here are the emails (newest first):
{email_list}

Respond in this exact JSON format:
{{
  "actionable": [
    {{"subject": "...", "from_email": "...", "action_needed": "one sentence describing what Max needs to do"}}
  ],
  "cold_emails": [
    {{"from_email": "...", "pitch_summary": "very brief description"}}
  ]
}}

Be strict. When in doubt, exclude. Only flag actionable emails where a real human outside Well Copy is clearly waiting on Max."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ── Slack ─────────────────────────────────────────────────────────────────────

def post_report(categorised):
    et = pytz.timezone("America/New_York")
    now = datetime.datetime.now(et)
    date_str = now.strftime("%B %-d, %Y")
    time_str = now.strftime("%-I:%M %p ET")

    actionable = categorised.get("actionable", [])
    cold       = categorised.get("cold_emails", [])

    lines = [f"<@{SLACK_MENTION_USER}> *Inbox Report — {date_str} ({time_str})*\n"]

    lines.append("*Actionable Emails*\n")
    if actionable:
        for i, item in enumerate(actionable, 1):
            lines.append(
                f"{i}. *{item['subject']}* | {item['from_email']} | {item['action_needed']}"
            )
    else:
        lines.append("_No actionable emails._")

    lines.append(f"\n---\n\n*Cold Email Count: {len(cold)}*")
    if cold:
        cold_list = ", ".join(f"{c['from_email']} ({c['pitch_summary']})" for c in cold)
        lines.append(cold_list)

    lines.append("\n---")
    lines.append("_Reports run at 7 AM & 3 PM ET, Mon–Fri_")

    message = "\n".join(lines)

    client = WebClient(token=SLACK_BOT_TOKEN)
    try:
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=message)
        print(f"[{now.strftime('%Y-%m-%d %H:%M ET')}] Report posted successfully.")
    except SlackApiError as e:
        print(f"Slack error: {e.response['error']}")
        raise


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching Gmail threads...")
    service  = get_gmail_service()
    threads  = fetch_threads(service, max_pages=3)
    print(f"Fetched {len(threads)} threads. Categorising...")
    categorised = categorise_emails(threads)
    print(f"Actionable: {len(categorised.get('actionable',[]))}  Cold: {len(categorised.get('cold_emails',[]))}")
    post_report(categorised)


if __name__ == "__main__":
    main()
