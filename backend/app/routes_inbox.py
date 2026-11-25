from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import db
from .db import get_session
from .mail import imap
from .mail.ingest import apply_to_project, ingest_raw
from .models import Event, InboxMessage, Project

router = APIRouter(prefix="/api/inbox")

MAX_UPLOAD = 15 * 1024 * 1024


class InboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    sender: str
    subject: str
    platform: str
    kind: str
    stage_hint: str | None
    url: str | None
    tracking_url: str | None
    campaign_url: str | None
    excerpt: str | None
    status: str
    match_reason: str | None
    project_id: int | None
    project_name: str | None = None
    event_id: int | None


class AssignIn(BaseModel):
    project_id: int


def _out(msg: InboxMessage) -> InboxOut:
    out = InboxOut.model_validate(msg)
    return out.model_copy(update={"project_name": msg.project.name if msg.project else None})


def _msg(session: Session, message_id: int) -> InboxMessage:
    msg = session.get(InboxMessage, message_id, options=[selectinload(InboxMessage.project)])
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.get("", response_model=list[InboxOut])
def list_inbox(
    status: str = Query(default="unsorted", pattern="^(unsorted|matched|ignored|all)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[InboxOut]:
    q = select(InboxMessage).options(selectinload(InboxMessage.project)).order_by(InboxMessage.received_at.desc())
    if status != "all":
        q = q.where(InboxMessage.status == status)
    return [_out(m) for m in session.scalars(q.limit(limit)).all()]


@router.get("/status")
def inbox_status(session: Session = Depends(get_session)) -> dict:
    cfg = imap.load_config()
    unsorted = session.query(InboxMessage).filter(InboxMessage.status == "unsorted").count()
    total = session.query(InboxMessage).count()
    return {
        "configured": cfg is not None,
        "host": cfg.host if cfg else None,
        "folder": cfg.folder if cfg else None,
        "interval_minutes": cfg.interval_minutes if cfg else None,
        "unsorted": unsorted,
        "total": total,
        **imap.status(session),
    }


@router.post("/sync")
def sync_now() -> dict:
    if imap.load_config() is None:
        raise HTTPException(
            status_code=409,
            detail="Email isn't set up. Set CROWDTRACKER_IMAP_HOST, _USER and _PASSWORD (see the README).",
        )
    assert db.SessionLocal is not None
    result = imap.sync_once(db.SessionLocal)
    if not result.ok and result.error == "A check is already running":
        raise HTTPException(status_code=409, detail="A check is already running. Try again in a minute.")
    return result.__dict__


@router.post("/upload", status_code=201)
async def upload(request: Request, session: Session = Depends(get_session)) -> dict:
    """Add one email by hand: send the raw .eml as the request body.

    curl --data-binary @update.eml -H 'Content-Type: message/rfc822' http://host/api/inbox/upload
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=422, detail="Send the raw email (.eml) as the request body.")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="That email is too large (15 MB max).")
    outcome, msg = ingest_raw(session, raw)
    if outcome == "skipped":
        raise HTTPException(
            status_code=422,
            detail="That email isn't from a crowdfunding platform crowdtracker knows (Kickstarter, BackerKit, "
            "Gamefound, PledgeManager, PledgeBox, Indiegogo), so it wasn't saved.",
        )
    assert msg is not None
    return {"outcome": outcome, "message": _out(_msg(session, msg.id)).model_dump(mode="json")}


@router.post("/{message_id}/assign", response_model=InboxOut)
def assign(message_id: int, payload: AssignIn, session: Session = Depends(get_session)) -> InboxOut:
    msg = _msg(session, message_id)
    project = session.get(Project, payload.project_id, options=[selectinload(Project.events)])
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    msg.match_reason = "assigned by you"
    apply_to_project(session, msg, project)
    session.commit()
    session.expire_all()
    return _out(_msg(session, message_id))


@router.post("/{message_id}/ignore", response_model=InboxOut)
def ignore(message_id: int, session: Session = Depends(get_session)) -> InboxOut:
    msg = _msg(session, message_id)
    if msg.event_id:
        event = session.get(Event, msg.event_id)
        if event is not None:
            session.delete(event)
    msg.status, msg.project_id, msg.event_id, msg.match_reason = "ignored", None, None, None
    session.commit()
    session.expire_all()
    return _out(_msg(session, message_id))


@router.post("/{message_id}/unsort", response_model=InboxOut)
def unsort(message_id: int, session: Session = Depends(get_session)) -> InboxOut:
    """Back to the tray (removes the timeline entry it made, if any)."""
    msg = _msg(session, message_id)
    if msg.event_id:
        event = session.get(Event, msg.event_id)
        if event is not None:
            session.delete(event)
    msg.status, msg.project_id, msg.event_id, msg.match_reason = "unsorted", None, None, None
    session.commit()
    session.expire_all()
    return _out(_msg(session, message_id))
