import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

try:
    from google.cloud import firestore
except Exception:  # pragma: no cover - handled at runtime in Cloud Run
    firestore = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStartIn(BaseModel):
    session_id: Optional[str] = None
    source: str = Field(default="desktop")
    app_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventIn(BaseModel):
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    ts: Optional[str] = None


class SessionEndIn(BaseModel):
    status: str = Field(default="completed")
    summary: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="JavPI Cloud Backend", version="1.0.0")
_db = None
_api_key = os.getenv("JAVPI_BACKEND_API_KEY", "").strip()
_collection = (
    os.getenv("JAVPI_FIRESTORE_COLLECTION", "javpi_sessions").strip()
    or "javpi_sessions"
)


def _require_api_key(x_api_key: Optional[str]) -> None:
    if not _api_key:
        return
    if x_api_key != _api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _get_db():
    global _db
    if _db is not None:
        return _db
    if firestore is None:
        raise HTTPException(
            status_code=500,
            detail="google-cloud-firestore is not installed",
        )
    _db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return _db


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "time": _utc_now(),
        "service": "javpi-cloud-backend",
    }


@app.post("/v1/sessions/start")
def start_session(
    payload: SessionStartIn,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)
    session_id = payload.session_id or str(uuid.uuid4())
    doc = {
        "session_id": session_id,
        "source": payload.source,
        "app_version": payload.app_version,
        "metadata": payload.metadata,
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "active",
    }
    db = _get_db()
    db.collection(_collection).document(session_id).set(doc)
    return {"status": "success", "session_id": session_id}


@app.post("/v1/sessions/{session_id}/events")
def add_event(
    session_id: str,
    payload: EventIn,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)
    db = _get_db()
    ref = db.collection(_collection).document(session_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Session not found")

    ts = payload.ts or _utc_now()
    event = {
        "type": payload.type,
        "payload": payload.payload,
        "ts": ts,
        "received_at": _utc_now(),
    }
    ref.collection("events").document(str(uuid.uuid4())).set(event)
    ref.set({"updated_at": _utc_now()}, merge=True)
    return {"status": "success"}


@app.post("/v1/sessions/{session_id}/end")
def end_session(
    session_id: str,
    payload: SessionEndIn,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)
    db = _get_db()
    ref = db.collection(_collection).document(session_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Session not found")

    duration_sec = None
    started_at = (snap.to_dict() or {}).get("started_at")
    if isinstance(started_at, str):
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_sec = max(
                0,
                int((datetime.now(timezone.utc) - start_dt).total_seconds()),
            )
        except Exception:
            duration_sec = None

    update_data = {
        "status": payload.status,
        "summary": payload.summary,
        "ended_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    if duration_sec is not None:
        update_data["duration_sec"] = duration_sec

    ref.set(update_data, merge=True)
    return {"status": "success"}


@app.get("/v1/sessions/{session_id}")
def get_session(session_id: str, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)
    db = _get_db()
    ref = db.collection(_collection).document(session_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Session not found")
    data = snap.to_dict() or {}
    data["session_id"] = session_id
    return {"status": "success", "session": data}
