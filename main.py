from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
from supabase import create_client, Client

# Brevo SDK
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

# ------------------------
# Config
# ------------------------
app = FastAPI(title="Patrol API")
ET = ZoneInfo("America/Toronto")

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing Supabase configuration (SUPABASE_URL / SUPABASE_KEY)")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Brevo config
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
if not BREVO_API_KEY:
    raise RuntimeError("Missing Brevo API key")

configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
brevo_client = sib_api_v3_sdk.TransactionalEmailsApi(
    sib_api_v3_sdk.ApiClient(configuration)
)

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
    """Send email via Brevo API"""
    if isinstance(to_emails, str):
        to_emails = [to_emails]

    try:
        email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": e} for e in to_emails],
            sender={"email": "arpanmahatra1999ad@gmail.com", "name": "Patrolio App"},
            subject=subject,
            html_content=body,
        )
        response = brevo_client.send_transac_email(email)
        print("✅ Email sent:", response)
    except ApiException as e:
        print("❌ Error sending email:", e)


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
def inactive_sessions(minutes: int, background_tasks: BackgroundTasks):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    response = supabase.table("patrol_sessions") \
        .select("id, first_name, last_name, sender_email") \
        .lt("photo_time", cutoff.isoformat()) \
        .eq("status", "active") \
        .limit(100) \
        .execute()

    expired_sessions = response.data
    sender_emails = [s["sender_email"] for s in expired_sessions]
    sender_emails = list(set(sender_emails))

    # Queue background email sending
    if sender_emails:
        background_tasks.add_task(
            send_email,
            sender_emails,
            "Patrolio: Gap in Patrol Session",
            "You have been found inactive for the last few minutes. Please keep sending photos."
        )

    if expired_sessions:
        summary_lines = [
            f"{s['first_name']} {s['last_name']} ({s['sender_email']})"
            for s in expired_sessions
        ]
        summary_subject = f"Patrolio: Inactive Sessions (>{minutes} mins)"
        summary_body = "The following guards have been inactive:\n\n" + "\n".join(summary_lines)
        background_tasks.add_task(send_email, "shivamminocha84@gmail.com", summary_subject, summary_body)

    return {
        "minutes_threshold": minutes,
        "expired_sessions_count": len(expired_sessions),
    }


@app.get("/cleanup_sessions/{minutes}")
def cleanup_sessions(minutes: int):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    response = supabase.table("patrol_sessions") \
        .delete() \
        .lt("photo_time", cutoff.isoformat()) \
        .execute()

    deleted_count = len(response.data)
    return {
        "minutes_threshold": minutes,
        "deleted_count": deleted_count,
        "deleted_sessions": response.data
    }


@app.get("/sessions")
def list_sessions():
    response = supabase.table("patrol_sessions").select("id").execute()
    session_ids = [r["id"] for r in response.data]
    return {
        "count": len(session_ids),
        "sample_session_ids": session_ids[:10],
    }
