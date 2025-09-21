from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import uuid
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

def send_email(to_email: str, subject: str, body: str):
    headers = {"X-API-KEY": BACKEND_API_KEY}
    data = {"to_email": to_email, "subject": subject, "text": body}
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

@app.get("/inactive_sessions/{minutes}")
def inactive_sessions(minutes: int):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    response = supabase.table("patrol_sessions") \
        .select("*") \
        .lt("photo_time", cutoff.isoformat()) \
        .eq("status", "active") \
        .execute()

    expired_sessions = response.data
    if not expired_sessions:
        return {"minutes_threshold": minutes, "expired_sessions": []}

    # Step 2: Notify all sender emails
    for session in expired_sessions:
        subject = "Patrolio: Gap in Patrol Session"
        body = f"Hi {session['first_name']} {session['last_name']}, You have been found inactive for last few minutes. Please keep sending photos."
        send_email(session["sender_email"], subject, body)

    # Step 3: Group by receiver email
    receivers_map = {}
    for session in expired_sessions:
        receiver = session["receiver_email"]
        if receiver not in receivers_map:
            receivers_map[receiver] = []
        receivers_map[receiver].append(
            f"{session['first_name']} {session['last_name']} ({session['sender_email']})"
        )

    # Step 4: Notify receivers
    for receiver, guards in receivers_map.items():
        subject = "Patrolio: Gaps in Patrol Sessions"
        body = "Following are the guards, who did not click photo in last few minutes.\n\n"
        body += "\n".join(guards)
        send_email(receiver, subject, body)

    return {
        "minutes_threshold": minutes,
        "expired_sessions": expired_sessions,
        "emails_sent_to_senders": len(expired_sessions),
        "emails_sent_to_receivers": len(receivers_map)
    }

@app.get("/sessions")
def list_sessions():
    response = supabase.table("patrol_sessions").select("*").execute()
    return {"count": len(response.data), "sessions": response.data}
