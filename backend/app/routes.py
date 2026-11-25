from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .db import get_session
from .models import (
    ACTION_STAGES,
    CLOSED_STAGES,
    EVENT_KINDS,
    PLATFORMS,
    REWARD_KINDS,
    STAGES,
    Event,
    Project,
    Reward,
)
from .periods import months_between, period_end, period_label
from .schemas import (
    EventCreate,
    EventOut,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
    RewardCreate,
    RewardOut,
    RewardUpdate,
    Summary,
)

router = APIRouter(prefix="/api")

# Stages a pledge can be in before anything has arrived. Receiving part of the
# rewards moves a pledge from any of these to "partial".
_PRE_DELIVERY = {"live", "funded", "survey_open", "survey_done", "charged", "address_locked", "shipping"}

_LOAD = (selectinload(Project.events), selectinload(Project.rewards))


def _today() -> date:
    """Today in CROWDTRACKER_TZ (falls back to TZ, then the server's local date)."""
    name = os.environ.get("CROWDTRACKER_TZ") or os.environ.get("TZ")
    if name:
        try:
            return datetime.now(ZoneInfo(name)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return date.today()


def _derived(project: Project, today: date) -> dict:
    """Fields computed from estimates, stage, rewards and events."""
    effective = project.current_est or project.original_est
    effective_end = period_end(effective) if effective else None
    is_open = project.stage not in CLOSED_STAGES
    overdue = bool(is_open and effective_end and effective_end < today)

    slip = None
    if project.original_est and project.current_est:
        slip = max(0, months_between(period_end(project.original_est), period_end(project.current_est)))

    months_late = None
    promised = project.original_est or project.current_est
    if project.stage == "delivered" and project.received_on and promised:
        promised_end = period_end(promised)
        months_late = 0 if project.received_on <= promised_end else months_between(promised_end, project.received_on)

    events = project.events
    return {
        "original_est_label": period_label(project.original_est),
        "current_est_label": period_label(project.current_est),
        "months_since_campaign": months_between(project.campaign_ended, today) if project.campaign_ended else None,
        "months_late": months_late,
        "rewards_received": sum(1 for r in project.rewards if r.received_on),
        "effective_est": effective,
        "effective_est_end": effective_end,
        "overdue": overdue,
        "months_overdue": max(1, months_between(effective_end, today)) if overdue and effective_end else 0,
        "slip_months": slip,
        "needs_action": project.stage in ACTION_STAGES,
        "last_event_on": max((e.occurred_on for e in events), default=None),
        "event_count": len(events),
    }


def _out(project: Project, today: date, *, detail: bool = False) -> ProjectOut | ProjectDetail:
    model = ProjectDetail if detail else ProjectOut
    base = model.model_validate(project)
    return base.model_copy(update=_derived(project, today))


def _get(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id, options=list(_LOAD))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _system_event(project: Project, kind: str, title: str, on: date) -> None:
    project.events.append(Event(occurred_on=on, kind=kind, title=title, source="system"))


def _sync_stage(project: Project, today: date) -> None:
    """Move the stage to match the rewards after one of them changed.

    Some received -> "partial"; all received -> "delivered". Cancelled pledges
    are left alone.
    """
    rewards = project.rewards
    if not rewards or project.stage == "cancelled":
        return
    got = [r.received_on for r in rewards if r.received_on]
    before = project.stage
    if len(got) == len(rewards):
        project.received_on = max(got)
        if before != "delivered":
            project.stage = "delivered"
            _system_event(project, "stage_change", f"Stage: {before} → delivered (all rewards received)", today)
    elif got and before in _PRE_DELIVERY | {"delivered"}:
        project.received_on = None
        if before != "partial":
            project.stage = "partial"
            _system_event(project, "stage_change", f"Stage: {before} → partial ({len(got)} of {len(rewards)} received)", today)
    elif not got and before in {"partial", "delivered"}:
        project.received_on = None
        project.stage = "shipping"
        _system_event(project, "stage_change", f"Stage: {before} → shipping (no rewards received)", today)


def _new_project(payload: ProjectCreate) -> Project:
    data = payload.model_dump(exclude={"rewards"})
    project = Project(**data)
    for i, reward in enumerate(payload.rewards):
        project.rewards.append(Reward(position=i, **reward.model_dump()))
    if project.rewards:
        got = [r.received_on for r in project.rewards if r.received_on]
        if got and project.stage not in CLOSED_STAGES:
            if len(got) == len(project.rewards):
                project.stage, project.received_on = "delivered", max(got)
            elif project.stage in _PRE_DELIVERY:
                project.stage = "partial"
    if project.stage == "delivered" and project.received_on is None:
        project.received_on = _today()
    return project


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta() -> dict:
    return {
        "platforms": PLATFORMS,
        "stages": STAGES,
        "event_kinds": EVENT_KINDS,
        "reward_kinds": REWARD_KINDS,
        "version": __version__,
    }


@router.get("/summary", response_model=Summary)
def summary(session: Session = Depends(get_session)) -> Summary:
    today = _today()
    projects = session.scalars(select(Project).options(*_LOAD)).all()
    derived = [(p, _derived(p, today)) for p in projects]
    return Summary(
        total=len(projects),
        open=sum(1 for p in projects if p.stage not in CLOSED_STAGES),
        overdue=sum(1 for _, d in derived if d["overdue"]),
        needs_action=sum(1 for _, d in derived if d["needs_action"]),
        partial=sum(1 for p in projects if p.stage == "partial"),
        delivered=sum(1 for p in projects if p.stage == "delivered"),
        cancelled=sum(1 for p in projects if p.stage == "cancelled"),
    )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    view: str = Query(default="all", pattern="^(all|open|overdue|action|partial|received|cancelled|closed)$"),
    session: Session = Depends(get_session),
) -> list[ProjectOut]:
    today = _today()
    projects = session.scalars(select(Project).options(*_LOAD)).all()
    out = [_out(p, today) for p in projects]
    keep = {
        "open": lambda p: p.stage not in CLOSED_STAGES,
        "overdue": lambda p: p.overdue,
        "action": lambda p: p.needs_action,
        "partial": lambda p: p.stage == "partial",
        "received": lambda p: p.stage == "delivered",
        "cancelled": lambda p: p.stage == "cancelled",
        "closed": lambda p: p.stage in CLOSED_STAGES,
    }.get(view)
    if keep:
        out = [p for p in out if keep(p)]
    # Soonest estimate first; projects with no estimate sink to the bottom.
    out.sort(key=lambda p: (p.effective_est_end is None, p.effective_est_end or date.max, p.name.lower()))
    return out


@router.post("/projects", response_model=ProjectDetail, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> ProjectDetail:
    project = _new_project(payload)
    session.add(project)
    session.commit()
    return _out(_get(session, project.id), _today(), detail=True)


@router.post("/import", status_code=201)
def import_projects(payload: list[ProjectCreate], session: Session = Depends(get_session)) -> dict:
    """Add many projects at once, e.g. `curl -X POST --json @projects.json .../api/import`."""
    session.add_all(_new_project(item) for item in payload)
    session.commit()
    return {"imported": len(payload)}


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectDetail:
    return _out(_get(session, project_id), _today(), detail=True)


@router.patch("/projects/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)
) -> ProjectDetail:
    project = _get(session, project_id)
    today = _today()
    changes = payload.model_dump(exclude_unset=True)

    for required in ("name", "funded_on", "stage", "currency"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} cannot be empty")

    # The timeline records estimate slips and stage moves on its own, so the
    # history builds up without anyone having to remember to log it.
    if "current_est" in changes and changes["current_est"] != project.current_est:
        before = period_label(project.current_est or project.original_est) or "no estimate"
        after = period_label(changes["current_est"]) or "no estimate"
        _system_event(project, "estimate_change", f"Estimate moved: {before} → {after}", today)

    new_stage = changes.get("stage", project.stage)
    if new_stage != project.stage:
        if new_stage == "delivered":
            # Received as a whole: anything not yet marked arrived on that day.
            when = changes.get("received_on") or project.received_on or today
            changes["received_on"] = when
            for reward in project.rewards:
                if reward.received_on is None:
                    reward.received_on = when
            _system_event(project, "delivery", "Received", when)
        else:
            _system_event(project, "stage_change", f"Stage: {project.stage} → {new_stage}", today)
            if project.stage == "delivered" and "received_on" not in changes:
                changes["received_on"] = None

    for field, value in changes.items():
        setattr(project, field, value)
    session.commit()
    session.expire_all()
    return _out(_get(session, project_id), today, detail=True)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(_get(session, project_id))
    session.commit()
    return Response(status_code=204)


# --- rewards -------------------------------------------------------------------


@router.post("/projects/{project_id}/rewards", response_model=ProjectDetail, status_code=201)
def add_reward(project_id: int, payload: RewardCreate, session: Session = Depends(get_session)) -> ProjectDetail:
    project = _get(session, project_id)
    today = _today()
    position = max((r.position for r in project.rewards), default=-1) + 1
    project.rewards.append(Reward(position=position, **payload.model_dump()))
    if payload.received_on:
        _system_event(project, "delivery", f"Received: {payload.name}", payload.received_on)
    _sync_stage(project, today)
    session.commit()
    session.expire_all()
    return _out(_get(session, project_id), today, detail=True)


@router.patch("/rewards/{reward_id}", response_model=ProjectDetail)
def update_reward(reward_id: int, payload: RewardUpdate, session: Session = Depends(get_session)) -> ProjectDetail:
    reward = session.get(Reward, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="Reward not found")
    changes = payload.model_dump(exclude_unset=True)
    for required in ("name", "kind"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} cannot be empty")

    project = _get(session, reward.project_id)
    today = _today()
    if "received_on" in changes and changes["received_on"] and changes["received_on"] != reward.received_on:
        name = changes.get("name", reward.name)
        _system_event(project, "delivery", f"Received: {name}", changes["received_on"])
    for field, value in changes.items():
        setattr(reward, field, value)
    _sync_stage(project, today)
    session.commit()
    session.expire_all()
    return _out(_get(session, project.id), today, detail=True)


@router.delete("/rewards/{reward_id}", response_model=ProjectDetail)
def delete_reward(reward_id: int, session: Session = Depends(get_session)) -> ProjectDetail:
    reward = session.get(Reward, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="Reward not found")
    project = _get(session, reward.project_id)
    project.rewards.remove(reward)
    _sync_stage(project, _today())
    session.commit()
    session.expire_all()
    return _out(_get(session, project.id), _today(), detail=True)


# --- events --------------------------------------------------------------------


@router.post("/projects/{project_id}/events", response_model=EventOut, status_code=201)
def add_event(project_id: int, payload: EventCreate, session: Session = Depends(get_session)) -> Event:
    project = _get(session, project_id)
    data = payload.model_dump()
    data["occurred_on"] = data["occurred_on"] or _today()
    event = Event(project_id=project.id, source="manual", **data)
    session.add(event)
    session.commit()
    return event


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, session: Session = Depends(get_session)) -> Response:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    session.delete(event)
    session.commit()
    return Response(status_code=204)
