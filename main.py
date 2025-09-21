from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import os
from supabase import create_client, Client

# ------------------------
# Config
# ------------------------
app = FastAPI(title="Patrol API")
ET = ZoneInfo("America/Toronto")

EMAIL_BACKEND_URL = "https://patrolio-email-backend.onrender.com/send-email"
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

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
    """Send email to one or multiple recipients"""
    if isinstance(to_emails, str):
        to_emails = [to_emails]

    headers = {"X-API-KEY": BACKEND_API_KEY}
    data = {"to_emails": to_emails, "subject": subject, "text": body}
    try:
        r = requests.post(EMAIL_BACKEND_URL, json=data, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ------------------------
# API Endpoints
# ------------------------

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
    response = supabase.table("patrol_sessions").update({
        "status": "ended"
    }).eq("id", session_id).execute()
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


from fastapi import BackgroundTasks


@app.get("/inactive_sessions/{minutes}")
def inactive_sessions(minutes: int):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    # Only fetch necessary fields, limit to 100 to prevent huge queries
    response = supabase.table("patrol_sessions") \
        .select("id, first_name, last_name, sender_email") \
        .lt("photo_time", cutoff.isoformat()) \
        .eq("status", "active") \
        .limit(100) \
        .execute()

    expired_sessions = response.data
    sender_emails = [s["sender_email"] for s in expired_sessions]

    # Send emails directly (synchronously)
    if sender_emails:
        subject = "Patrolio: Gap in Patrol Session"
        body = "You have been found inactive for the last few minutes. Please keep sending photos."
        send_email(sender_emails, subject, body)

    # Summary email to admin
    if expired_sessions:
        summary_lines = [
            f"{s['first_name']} {s['last_name']} ({s['sender_email']})"
            for s in expired_sessions
        ]
        summary_subject = f"Patrolio: Inactive Sessions (>{minutes} mins)"
        summary_body = "The following guards have been inactive:\n\n" + "\n".join(summary_lines)
        send_email("shivamminocha84@gmail.com", summary_subject, summary_body)

    # ✅ Return only very small response
    return {
        "minutes_threshold": minutes,
        "expired_sessions_count": len(expired_sessions),
        "emails_sent_to_senders": len(sender_emails),
        "summary_sent_to": "shivamminocha84@gmail.com"
    }


@app.get("/sessions")
def list_sessions():
    response = supabase.table("patrol_sessions").select("*").execute()
    return {"count": len(response.data), "sessions": response.data}
