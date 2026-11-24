from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .db import get_session
from .models import ACTION_STAGES, CLOSED_STAGES, EVENT_KINDS, PLATFORMS, STAGES, Event, Project
from .periods import months_between, period_end, period_label
from .schemas import (
    EventCreate,
    EventOut,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
    Summary,
)

router = APIRouter(prefix="/api")


def _today() -> date:
    return date.today()


def _derived(project: Project, today: date) -> dict:
    """Fields computed from estimates, stage and events."""
    effective = project.current_est or project.original_est
    effective_end = period_end(effective) if effective else None
    is_open = project.stage not in CLOSED_STAGES
    overdue = bool(is_open and effective_end and effective_end < today)

    slip = None
    if project.original_est and project.current_est:
        slip = max(0, months_between(period_end(project.original_est), period_end(project.current_est)))

    events = project.events
    return {
        "original_est_label": period_label(project.original_est),
        "current_est_label": period_label(project.current_est),
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
    project = session.get(Project, project_id, options=[selectinload(Project.events)])
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _system_event(project: Project, kind: str, title: str, today: date) -> None:
    project.events.append(Event(occurred_on=today, kind=kind, title=title, source="system"))


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta() -> dict:
    return {"platforms": PLATFORMS, "stages": STAGES, "event_kinds": EVENT_KINDS, "version": __version__}


@router.get("/summary", response_model=Summary)
def summary(session: Session = Depends(get_session)) -> Summary:
    today = _today()
    projects = session.scalars(select(Project).options(selectinload(Project.events))).all()
    derived = [(p, _derived(p, today)) for p in projects]
    return Summary(
        total=len(projects),
        open=sum(1 for p in projects if p.stage not in CLOSED_STAGES),
        overdue=sum(1 for _, d in derived if d["overdue"]),
        needs_action=sum(1 for _, d in derived if d["needs_action"]),
        delivered=sum(1 for p in projects if p.stage == "delivered"),
    )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    view: str = Query(default="all", pattern="^(all|open|overdue|action|closed)$"),
    session: Session = Depends(get_session),
) -> list[ProjectOut]:
    today = _today()
    projects = session.scalars(select(Project).options(selectinload(Project.events))).all()
    out = [_out(p, today) for p in projects]
    if view == "open":
        out = [p for p in out if p.stage not in CLOSED_STAGES]
    elif view == "overdue":
        out = [p for p in out if p.overdue]
    elif view == "action":
        out = [p for p in out if p.needs_action]
    elif view == "closed":
        out = [p for p in out if p.stage in CLOSED_STAGES]
    # Soonest estimate first; projects with no estimate sink to the bottom.
    out.sort(key=lambda p: (p.effective_est_end is None, p.effective_est_end or date.max, p.name.lower()))
    return out


@router.post("/projects", response_model=ProjectDetail, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> ProjectDetail:
    project = Project(**payload.model_dump())
    session.add(project)
    session.commit()
    return _out(_get(session, project.id), _today(), detail=True)


@router.post("/import", status_code=201)
def import_projects(payload: list[ProjectCreate], session: Session = Depends(get_session)) -> dict:
    """Add many projects at once, e.g. `curl -X POST --json @projects.json .../api/import`."""
    session.add_all(Project(**item.model_dump()) for item in payload)
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
    if "stage" in changes and changes["stage"] != project.stage:
        _system_event(project, "stage_change", f"Stage: {project.stage} → {changes['stage']}", today)

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
