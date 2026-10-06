"""
MartEva Bot v2.1 - Server-ready
OAuth flow: Run locally first to generate token.json, then deploy.
"""

import os
import datetime
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import anthropic

# --- CONFIG ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/gmail.readonly"]
DB_PATH = "/tmp/marteva_bot.db"

# --- DB ---
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, amount REAL, category TEXT, description TEXT, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, client TEXT, finding TEXT, status TEXT DEFAULT 'open', date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, subject TEXT, duration_min INTEGER, topic TEXT, date TEXT)""")
    conn.commit()
    conn.close()

# --- GOOGLE ---
import json
from google.oauth2 import service_account

def get_google_creds():
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_json:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set in Railway")

import os, json
from google.oauth2.credentials import Credentials

def get_gmail_creds():
    creds_json = os.environ.get("GMAIL_TOKEN")
    if not creds_json:
        raise RuntimeError("GMAIL_TOKEN not set in Railway")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_authorized_user_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar"
        ]
    )
    return creds
creds = get_gmail_creds()
gmail_service = build("gmail", "v1", credentials=creds)
calendar_service = build("calendar", "v3", credentials=creds)
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
import base64

def get_body(msg):
    if 'parts' in msg['payload']:
        for part in msg['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body']['data']
                return base64.urlsafe_b64decode(data).decode('utf-8')
    else:
        data = msg['payload']['body']['data']
        return base64.urlsafe_b64decode(data).decode('utf-8')
    return ""

def summarize_email(text):
    prompt = f"Summarize this email in 2 sentences:\n\n{text}"
    response = ai_client.completions.create(
        model="claude-3-opus-20240229",
        max_tokens=200,
        prompt=prompt
    )
    return response.completion.strip()
    
def fetch_and_summarize():
    results = gmail_service.users().messages().list(userId='me', labelIds=['UNREAD']).execute()
    messages = results.get('messages', [])
    summaries = []

    for message in messages:
        msg = gmail_service.users().messages().get(userId='me', id=message['id']).execute()
        subject = next(h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject')
        body = get_body(msg)
        summary = summarize_email(body)
        summaries.append(f"📧 {subject}: {summary}")

    return summaries

if __name__ == "__main__":
    summaries = fetch_and_summarize()
    for s in summaries:
        print(s)

SYSTEM_PROMPT = """You are MartEva, Muchai's personal study and work assistant.
Context: Muchai is doing an MBA (Finance) and works as an Audit Assistant in Nairobi, Kenya.
Be concise, practical, and use examples from finance/auditing when relevant.
For calculations, show step-by-step work. Use KES for currency examples."""

AUDIT_TEMPLATES = {
    "cash": """💰 *CASH AUDIT CHECKLIST*
□ Verify cash count sheet
□ Trace to general ledger
□ Check segregation of duties
□ Review bank reconciliations
□ Test cut-off
□ Confirm signatories
□ Review petty cash vouchers""",
    "inventory": """📦 *INVENTORY AUDIT CHECKLIST*
□ Physical count observation
□ Test count accuracy
□ Verify pricing & valuation
□ Check FIFO/LIFO/WAC consistency
□ Review obsolete stock provision
□ Test cut-off""",
    "payroll": """👥 *PAYROLL AUDIT CHECKLIST*
□ Verify employee master file
□ Check ghost employees
□ Review overtime approvals
□ Test payroll tax calculations
□ Confirm statutory deductions (PAYE, NHIF, NSSF)""",
    "receivables": """📋 *RECEIVABLES AUDIT CHECKLIST*
□ Send confirmations to top debtors
□ Review aged debtors schedule
□ Test bad debt provision
□ Check subsequent receipts
□ Verify credit limits""",
}

# --- COMMANDS ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 *Hey Muchai! MartEva v2.1 online*\n\n"
        "*Calendar & Email:*\n"
        "/remind `<text> | <YYYY-MM-DD HH:MM>`\n"
        "/inbox — unread emails\n"
        "/today — today's calendar\n\n"
        "*AI:*\n"
        "/ask `<question>`\n"
        "/note — send photo of notes\n\n"
        "*Work tools:*\n"
        "/expense `<amount> <category> <desc>`\n"
        "/expenses — this month\n"
        "/audit `<cash|inventory|payroll|receivables>`\n"
        "/auditnote `<client> <finding>`\n\n"
        "*Study:*\n"
        "/study `<subject> <minutes> <topic>`\n"
        "/progress — study stats",
        parse_mode="Markdown"
    )

async def remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        parts = " ".join(ctx.args).split("|")
        text = parts[0].strip()
        when = datetime.datetime.strptime(parts[1].strip(), "%Y-%m-%d %H:%M")
        event = {"summary": text,
                 "start": {"dateTime": when.isoformat(), "timeZone": "Africa/Nairobi"},
                 "end": {"dateTime": (when + datetime.timedelta(minutes=30)).isoformat(), "timeZone": "Africa/Nairobi"}}
        calendar_service.events().insert(calendarId="primary", body=event).execute()
        await update.message.reply_text(f"✅ Reminder set: *{text}* at {when.strftime('%b %d, %H:%M')}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Format: `/remind <text> | <YYYY-MM-DD HH:MM>`\nError: {e}", parse_mode="Markdown")

async def ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    question = " ".join(ctx.args)
    if not question:
        await update.message.reply_text("Usage: `/ask <question>`", parse_mode="Markdown")
        return
    msg = await update.message.reply_text("🤔 Thinking...")
    try:
        response = ai_client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}]
        )
        await msg.edit_text(response.content[0].text)
    except Exception as e:
        await msg.edit_text(f"❌ AI error: {e}")

async def inbox(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        results = gmail_service.users().messages().list(userId="me", q="is:unread", maxResults=5).execute()
        messages = results.get("messages", [])
        if not messages:
            await update.message.reply_text("📭 Inbox is empty.")
            return
        reply = "📧 *Unread emails:*\n\n"
        for m in messages:
            msg = gmail_service.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "From"]).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            reply += f"• *{headers.get('Subject', '(no subject)')}*\n  from {headers.get('From', 'unknown')}\n\n"
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Gmail error: {e}")

async def today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        end = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + "Z"
        events = calendar_service.events().list(calendarId="primary", timeMin=now, timeMax=end, singleEvents=True).execute()
        items = events.get("items", [])
        if not items:
            await update.message.reply_text("📅 Nothing scheduled today.")
            return
        reply = "📅 *Today:*\n\n"
        for e in items:
            start = e["start"].get("dateTime", e["start"].get("date"))
            reply += f"• {start[11:16]} — {e['summary']}\n"
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Calendar error: {e}")

async def note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await update.message.reply_text("📝 Note received. (Vision analysis: wire GPT-4V or Claude Vision in the code)")
    else:
        await update.message.reply_text("Send a photo of your notes.")

async def expense(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        args = ctx.args
        amount = float(args[0])
        category = args[1]
        description = " ".join(args[2:]) if len(args) > 2 else ""
        conn = db()
        conn.execute("INSERT INTO expenses (user_id, amount, category, description, date) VALUES (?, ?, ?, ?, ?)",
                     (update.effective_user.id, amount, category, description, datetime.date.today().isoformat()))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"💸 Logged: *KES {amount:,.2f}* — {category}\n{description}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text("❌ Format: `/expense <amount> <category> <description>`", parse_mode="Markdown")

async def expenses(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    month = datetime.date.today().strftime("%Y-%m")
    conn = db()
    rows = conn.execute("SELECT amount, category, description, date FROM expenses WHERE user_id=? AND date LIKE ? ORDER BY date DESC",
                        (update.effective_user.id, f"{month}%")).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📊 No expenses logged this month.")
        return
    total = sum(r[0] for r in rows)
    reply = f"📊 *This month's expenses:*\n\n"
    by_cat = {}
    for r in rows:
        by_cat[r[1]] = by_cat.get(r[1], 0) + r[0]
    for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
        reply += f"• {cat}: KES {amt:,.2f}\n"
    reply += f"\n*Total: KES {total:,.2f}*"
    await update.message.reply_text(reply, parse_mode="Markdown")

async def audit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or ctx.args[0] not in AUDIT_TEMPLATES:
        await update.message.reply_text("❌ Usage: `/audit <cash|inventory|payroll|receivables>`", parse_mode="Markdown")
        return
    await update.message.reply_text(AUDIT_TEMPLATES[ctx.args[0]], parse_mode="Markdown")

async def auditnote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        client = ctx.args[0]
        finding = " ".join(ctx.args[1:])
        conn = db()
        conn.execute("INSERT INTO audit_notes (user_id, client, finding, date) VALUES (?, ?, ?, ?)",
                     (update.effective_user.id, client, finding, datetime.date.today().isoformat()))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"📝 Audit note saved for *{client}*", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Format: `/auditnote <client> <finding>`", parse_mode="Markdown")

async def study(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        subject = ctx.args[0]
        minutes = int(ctx.args[1])
        topic = " ".join(ctx.args[2:]) if len(ctx.args) > 2 else ""
        conn = db()
        conn.execute("INSERT INTO study_sessions (user_id, subject, duration_min, topic, date) VALUES (?, ?, ?, ?, ?)",
                     (update.effective_user.id, subject, minutes, topic, datetime.date.today().isoformat()))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"📚 Logged: *{minutes} min* on {subject}\n{topic}", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Format: `/study <subject> <minutes> <topic>`", parse_mode="Markdown")

async def progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = db()
    week = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    rows = conn.execute("SELECT subject, SUM(duration_min) FROM study_sessions WHERE user_id=? AND date >= ? GROUP BY subject",
                        (update.effective_user.id, week)).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📚 No study sessions this week. Start one with `/study`")
        return
    total = sum(r[1] for r in rows)
    reply = f"📚 *This week's study:*\n\n"
    for subj, mins in sorted(rows, key=lambda x: -x[1]):
        hrs = mins / 60
        reply += f"• {subj}: {hrs:.1f}h ({mins} min)\n"
    reply += f"\n*Total: {total/60:.1f}h*"
    await update.message.reply_text(reply, parse_mode="Markdown")

# --- MAIN ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    for cmd, handler in [("start", start), ("remind", remind), ("ask", ask), ("inbox", inbox),
                          ("today", today), ("note", note), ("expense", expense), ("expenses", expenses),
                          ("audit", audit), ("auditnote", auditnote), ("study", study), ("progress", progress)]:
        app.add_handler(CommandHandler(cmd, handler))
    print("MartEva v2.1 running...")
    app.run_polling()
