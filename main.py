from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict
import uuid
import requests
import os

app = FastAPI(title="Patrol API")

# ------------------------
# Config
# ------------------------
ET = ZoneInfo("America/Toronto")
EMAIL_BACKEND_URL = "https://patrolio-email-backend.onrender.com/send-email"
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY")

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
# In-memory storage
# ------------------------
patrol_sessions: Dict[str, dict] = {}

def now_iso():
    return datetime.now(ET).replace(microsecond=0).isoformat()

def parse_iso(ts: str):
    return datetime.fromisoformat(ts)

# ------------------------
# Helper: Send email via backend
# ------------------------
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
    session_id = str(uuid.uuid4())
    start_time = now_iso()
    patrol_sessions[session_id] = {
        "start_time": start_time,
        "photo_time": start_time,
        "first_name": data.first_name,
        "last_name": data.last_name,
        "sender_email": data.sender_email,
        "receiver_email": data.receiver_email
    }
    return {"message": "patrol started", "session_id": session_id, "data": patrol_sessions[session_id]}

@app.post("/pause_patrol/{session_id}")
def pause_patrol(session_id: str):
    session = patrol_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    session["photo_time"] = now_iso()
    return {"message": "photo_time updated", "data": session}

@app.post("/end_patrol/{session_id}")
def end_patrol(session_id: str):
    session = patrol_sessions.pop(session_id, None)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"message": "patrol ended", "ended_session": session}

@app.get("/photo_time/{session_id}")
def get_photo_time(session_id: str):
    session = patrol_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "photo_time": session["photo_time"]}

@app.post("/get_session_id")
def get_session_id(query: LookupPatrol):
    for session_id, data in patrol_sessions.items():
        if (
            data["first_name"] == query.first_name
            and data["last_name"] == query.last_name
            and data["sender_email"] == query.sender_email
            and data["receiver_email"] == query.receiver_email
        ):
            return {"session_id": session_id, "data": data}
    raise HTTPException(status_code=404, detail="no matching session found")

@app.get("/all_session_ids")
def all_session_ids():
    return {"count": len(patrol_sessions), "session_ids": list(patrol_sessions.keys())}

@app.get("/inactive_sessions/{minutes}")
def inactive_sessions(minutes: int):
    now = datetime.now(ET)
    expired_sessions = []

    # Step 1: Find inactive sessions
    for session_id, data in patrol_sessions.items():
        photo_time = parse_iso(data["photo_time"])
        diff_minutes = (now - photo_time).total_seconds() / 60
        if diff_minutes > minutes:
            expired_sessions.append({
                "session_id": session_id,
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "sender_email": data["sender_email"],
                "receiver_email": data["receiver_email"],
                "diff_minutes": round(diff_minutes, 2)
            })

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

    # Step 4: Notify all receiver emails (one per receiver)
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
    return {"count": len(patrol_sessions), "sessions": patrol_sessions}
