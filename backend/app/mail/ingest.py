"""Store parsed emails and turn matched ones into timeline events."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import STAGES, Event, InboxMessage, Project
from .match import match_project
from .parse import ParsedMail, parse_message, summary

# Stages an email may move a pledge forward from. Once something has arrived
# (partial/delivered) or the pledge is cancelled, the rewards decide, not mail.
_EMAIL_MOVABLE = {"live", "funded", "survey_open", "survey_done", "charged", "address_locked", "shipping"}


def _rank(stage: str) -> int:
    return STAGES.index(stage) if stage in STAGES else -1


def advance_stage(project: Project, hint: str | None) -> bool:
    """Move the pledge forward to `hint`. Never moves it backwards."""
    if not hint or project.stage not in _EMAIL_MOVABLE or _rank(hint) <= _rank(project.stage):
        return False
    before = project.stage
    project.stage = hint
    project.events.append(
        Event(
            occurred_on=clock.today(),
            kind="stage_change",
            title=f"Stage: {before} → {hint} (from email)",
            source="system",
        )
    )
    return True


def apply_to_project(session: Session, msg: InboxMessage, project: Project) -> Event:
    """Add the email to the pledge's timeline (once) and advance its stage."""
    if msg.event_id:
        existing = session.get(Event, msg.event_id)
        if existing is not None and existing.project_id == project.id:
            return existing
        if existing is not None:
            session.delete(existing)
    event = Event(
        occurred_on=clock.local_date(msg.received_at),
        kind=msg.kind if msg.kind != "note" else "note",
        title=msg.subject[:300],
        body=summary(msg.excerpt or ""),
        url=msg.tracking_url or msg.url,
        source="email",
    )
    project.events.append(event)
    advance_stage(project, msg.stage_hint)
    session.flush()
    msg.project_id = project.id
    msg.event_id = event.id
    msg.status = "matched"
    return event


def _new_message(parsed: ParsedMail) -> InboxMessage:
    return InboxMessage(
        message_id=parsed.message_id,
        received_at=parsed.received_at,
        sender=parsed.sender,
        subject=parsed.subject,
        platform=parsed.platform,
        kind=parsed.kind,
        stage_hint=parsed.stage_hint,
        url=parsed.url,
        tracking_url=parsed.tracking_url,
        campaign_url=parsed.campaign_url,
        excerpt=parsed.excerpt,
        status="unsorted",
    )


def ingest_raw(session: Session, raw: bytes) -> tuple[str, InboxMessage | None]:
    """Process one raw email. Returns (outcome, message).

    outcome is "skipped" (not platform mail; nothing stored), "duplicate",
    "matched" or "unsorted".
    """
    parsed = parse_message(raw)
    if parsed is None:
        return "skipped", None
    existing = session.scalar(select(InboxMessage).where(InboxMessage.message_id == parsed.message_id))
    if existing is not None:
        return "duplicate", existing

    msg = _new_message(parsed)
    session.add(msg)
    projects = session.scalars(select(Project).where(Project.stage != "cancelled")).all()
    found = match_project(parsed.subject, parsed.text, parsed.links, list(projects))
    if found:
        project = session.get(Project, found.project_id)
        assert project is not None
        msg.match_reason = found.reason
        apply_to_project(session, msg, project)
    session.commit()
    return msg.status, msg
