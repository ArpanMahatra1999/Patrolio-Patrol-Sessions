from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import smtplib
from email.message import EmailMessage
from supabase import create_client, Client

# ------------------------
# Config
# ------------------------
app = FastAPI(title="Patrol API")
ET = ZoneInfo("America/Toronto")

# Gmail SMTP credentials
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([EMAIL_USER, EMAIL_APP_PASSWORD]):
    raise RuntimeError("Missing Gmail SMTP configuration (EMAIL_USER / EMAIL_APP_PASSWORD)")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing Supabase configuration (SUPABASE_URL / SUPABASE_KEY)")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ------------------------
# Data Models
# ------------------------
class StartPatrol(BaseModel):
    first_name: str
    last_name: str
    sender_email: EmailStr
    receiver_email: EmailStr


class LookupPatrol(BaseModel):
    first_name: str
    last_name: str
    sender_email: EmailStr
    receiver_email: EmailStr


# ------------------------
# Helpers
# ------------------------
def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def send_email(to_emails, subject: str, body: str):
    """Send email via Gmail SMTP"""
    if isinstance(to_emails, str):
        to_emails = [to_emails]

    msg = EmailMessage()
    msg["From"] = EMAIL_USER
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print("Error sending email:", e)


# ------------------------
# API Endpoints
# ------------------------
@app.post("/")
def base():
    return {"status": "APIs working"}


@app.post("/start_patrol")
def start_patrol(data: StartPatrol):
    response = supabase.table("patrol_sessions").insert({
        "first_name": data.first_name,
        "last_name": data.last_name,
        "sender_email": data.sender_email,
        "receiver_email": data.receiver_email,
        "start_time": now_iso(),
        "photo_time": now_iso(),
        "status": "active"
    }).execute()
    return {"message": "patrol started", "data": response.data[0]}


@app.post("/pause_patrol/{session_id}")
def pause_patrol(session_id: str):
    response = supabase.table("patrol_sessions").update({
        "photo_time": now_iso()
    }).eq("id", session_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="session not found")
    return {"message": "photo_time updated", "data": response.data[0]}


@app.post("/end_patrol/{session_id}")
def end_patrol(session_id: str):
    response = supabase.table("patrol_sessions").delete().eq("id", session_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="session not found")
    return {"message": "patrol ended", "data": response.data[0]}


@app.get("/photo_time/{session_id}")
def get_photo_time(session_id: str):
    response = supabase.table("patrol_sessions").select("photo_time").eq("id", session_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "photo_time": response.data[0]["photo_time"]}


@app.post("/get_session_id")
def get_session_id(query: LookupPatrol):
    response = supabase.table("patrol_sessions").select("*") \
        .eq("first_name", query.first_name) \
        .eq("last_name", query.last_name) \
        .eq("sender_email", query.sender_email) \
        .eq("receiver_email", query.receiver_email) \
        .eq("status", "active") \
        .execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="no matching session found")
    return {"session_id": response.data[0]["id"], "data": response.data[0]}


@app.get("/all_session_ids")
def all_session_ids():
    response = supabase.table("patrol_sessions").select("id").execute()
    return {"count": len(response.data), "session_ids": [r["id"] for r in response.data]}


@app.get("/inactive_sessions/{minutes}")
def inactive_sessions(minutes: int):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    # Only fetch the minimal fields needed
    response = supabase.table("patrol_sessions") \
        .select("id, first_name, last_name, sender_email") \
        .lt("photo_time", cutoff.isoformat()) \
        .eq("status", "active") \
        .limit(100) \
        .execute()

    expired_sessions = response.data
    sender_emails = [s["sender_email"] for s in expired_sessions]

    # Send email alerts
    if sender_emails:
        subject = "Patrolio: Gap in Patrol Session"
        body = "You have been found inactive for the last few minutes. Please keep sending photos."
        send_email(sender_emails, subject, body)

    # Send summary email to admin
    if expired_sessions:
        summary_lines = [
            f"{s['first_name']} {s['last_name']} ({s['sender_email']})"
            for s in expired_sessions
        ]
        summary_subject = f"Patrolio: Inactive Sessions (>{minutes} mins)"
        summary_body = "The following guards have been inactive:\n\n" + "\n".join(summary_lines)
        send_email("shivamminocha84@gmail.com", summary_subject, summary_body)

    # ✅ Return only small JSON to cronjob.org
    return {
        "minutes_threshold": minutes,
        "expired_sessions_count": len(expired_sessions),
        "emails_sent": len(sender_emails),
    }


@app.get("/sessions")
def list_sessions():
    # Only fetch IDs to keep response small
    response = supabase.table("patrol_sessions").select("id").execute()
    session_ids = [r["id"] for r in response.data]

    # ✅ Always return small response
    return {
        "count": len(session_ids),
        "sample_session_ids": session_ids[:10],  # preview max 10
    }
