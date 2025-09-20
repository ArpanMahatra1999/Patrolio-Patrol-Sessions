from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Dict
import uuid

app = FastAPI(title="Patrol API")

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

# In-memory store (ephemeral — will be lost on service restart)
patrol_sessions: Dict[str, dict] = {}

def now_iso():
    # UTC ISO timestamp without microseconds, add 'Z' to indicate UTC
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

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

# Optional: debug endpoints (you can remove in production)
@app.get("/sessions")
def list_sessions():
    return {"count": len(patrol_sessions), "sessions": patrol_sessions}

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

@app.get("/photo_time/{session_id}")
def get_photo_time(session_id: str):
    session = patrol_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session_id,
        "photo_time": session["photo_time"]
    }

