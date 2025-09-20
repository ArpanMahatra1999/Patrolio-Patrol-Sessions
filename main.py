from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict
import uuid

app = FastAPI(title="Patrol API")


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

# Use Eastern Time (ET)
ET = ZoneInfo("America/Toronto")


def now_iso():
    """Returns current ET time in ISO format."""
    return datetime.now(ET).replace(microsecond=0).isoformat()


def parse_iso(ts: str):
    """Parse ISO timestamp back to datetime (ET)."""
    return datetime.fromisoformat(ts)


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
    for session_id, data in patrol_sessions.items():
        photo_time = parse_iso(data["photo_time"])
        diff_minutes = (now - photo_time).total_seconds() / 60
        if diff_minutes > minutes:
            expired_sessions.append({"session_id": session_id, "diff_minutes": round(diff_minutes, 2)})
    return {"minutes_threshold": minutes, "expired_sessions": expired_sessions}


@app.get("/sessions")
def list_sessions():
    return {"count": len(patrol_sessions), "sessions": patrol_sessions}
