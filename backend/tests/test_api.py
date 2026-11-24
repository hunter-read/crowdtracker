from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app import db, routes
from app.main import create_app
from app.periods import months_between, period_end, period_label, validate_period
from app.seed import EXAMPLE_SEED, seed_if_empty

TODAY = date(2026, 11, 23)


@pytest.fixture
def client(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.engine = engine
    db.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    from app import models  # noqa: F401

    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(routes, "_today", lambda: TODAY)
    monkeypatch.delenv("CROWDTRACKER_SEED_FILE", raising=False)
    with TestClient(create_app()) as c:
        yield c
    db.Base.metadata.drop_all(engine)
    db.engine = None
    db.SessionLocal = None


def make(client, **overrides):
    body = {"name": "Test Project", "funded_on": "kickstarter"} | overrides
    res = client.post("/api/projects", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# --- periods -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "end", "label"),
    [
        ("2026", date(2026, 12, 31), "2026"),
        ("2026-Q4", date(2026, 12, 31), "Q4 2026"),
        ("2027-Q1", date(2027, 3, 31), "Q1 2027"),
        ("2026-10", date(2026, 10, 31), "Oct 2026"),
        ("2024-02", date(2024, 2, 29), "Feb 2024"),
        ("2026-07-04", date(2026, 7, 4), "Jul 4, 2026"),
    ],
)
def test_period_end_and_label(period, end, label):
    assert period_end(period) == end
    assert period_label(period) == label


@pytest.mark.parametrize("bad", ["26", "2026-13", "2026-Q5", "late 2026", "2026-00", "2026-1"])
def test_bad_periods_rejected(bad):
    with pytest.raises(ValueError):
        validate_period(bad)


def test_period_normalised():
    assert validate_period(" 2026-q4 ") == "2026-Q4"
    assert validate_period("") is None
    assert months_between(date(2025, 10, 31), date(2026, 12, 31)) == 14


# --- projects ----------------------------------------------------------------


def test_create_and_get(client):
    created = make(client, original_est="2027-08", category="TTRPG")
    got = client.get(f"/api/projects/{created['id']}").json()
    assert got["name"] == "Test Project"
    assert got["original_est_label"] == "Aug 2027"
    assert got["overdue"] is False
    assert got["events"] == []


def test_overdue_uses_current_estimate_when_present(client):
    late = make(client, name="Late", original_est="2025-12")
    slipped = make(client, name="Slipped", original_est="2025-10", current_est="2026-Q4")
    assert late["overdue"] is True
    assert late["months_overdue"] == 11
    # Past its original date, but the creator's new date has not passed yet.
    assert slipped["overdue"] is False
    assert slipped["slip_months"] == 14


def test_closed_projects_are_never_overdue(client):
    done = make(client, original_est="2024-01", stage="delivered")
    assert done["overdue"] is False


def test_views_and_sort_order(client):
    make(client, name="B later", original_est="2027-09")
    make(client, name="A overdue", original_est="2026-07")
    make(client, name="No estimate")
    make(client, name="Survey", original_est="2027-01", stage="survey_open")
    make(client, name="Done", original_est="2024-01", stage="delivered")

    names = [p["name"] for p in client.get("/api/projects").json()]
    assert names == ["Done", "A overdue", "Survey", "B later", "No estimate"]
    assert [p["name"] for p in client.get("/api/projects?view=overdue").json()] == ["A overdue"]
    assert [p["name"] for p in client.get("/api/projects?view=action").json()] == ["Survey"]
    assert [p["name"] for p in client.get("/api/projects?view=closed").json()] == ["Done"]
    assert len(client.get("/api/projects?view=open").json()) == 4
    assert client.get("/api/projects?view=nope").status_code == 422

    summary = client.get("/api/summary").json()
    assert summary == {"total": 5, "open": 4, "overdue": 1, "needs_action": 1, "delivered": 1}


def test_patch_logs_estimate_and_stage_changes(client):
    p = make(client, original_est="2026-12")
    res = client.patch(f"/api/projects/{p['id']}", json={"current_est": "2027-Q3", "stage": "survey_open"})
    assert res.status_code == 200
    body = res.json()
    assert body["current_est_label"] == "Q3 2027"
    assert body["needs_action"] is True
    titles = sorted(e["title"] for e in body["events"])
    assert titles == ["Estimate moved: Dec 2026 → Q3 2027", "Stage: funded → survey_open"]
    assert all(e["source"] == "system" for e in body["events"])

    # Sending the same values again must not log duplicates.
    again = client.patch(f"/api/projects/{p['id']}", json={"current_est": "2027-Q3", "stage": "survey_open"})
    assert len(again.json()["events"]) == 2


def test_patch_is_partial_and_can_clear_fields(client):
    p = make(client, creator="MCDM", notes="hello", current_est="2027")
    body = client.patch(f"/api/projects/{p['id']}", json={"notes": None}).json()
    assert body["notes"] is None
    assert body["creator"] == "MCDM"
    assert body["current_est"] == "2027"
    assert client.patch(f"/api/projects/{p['id']}", json={"name": None}).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"funded_on": "patreon"},
        {"stage": "lost"},
        {"original_est": "soon"},
        {"campaign_url": "javascript:alert(1)"},
        {"pledge_amount": -5},
        {"name": ""},
    ],
)
def test_validation(client, bad):
    res = client.post("/api/projects", json={"name": "X", "funded_on": "kickstarter"} | bad)
    assert res.status_code == 422


def test_events_and_cascade_delete(client):
    p = make(client)
    res = client.post(
        f"/api/projects/{p['id']}/events",
        json={"kind": "update", "title": "Update #12: printing started", "occurred_on": "2026-11-01"},
    )
    assert res.status_code == 201
    event = res.json()
    assert event["source"] == "manual"

    defaulted = client.post(f"/api/projects/{p['id']}/events", json={"title": "Note"}).json()
    assert defaulted["occurred_on"] == TODAY.isoformat()

    detail = client.get(f"/api/projects/{p['id']}").json()
    assert detail["event_count"] == 2
    assert detail["last_event_on"] == TODAY.isoformat()
    assert [e["title"] for e in detail["events"]] == ["Note", "Update #12: printing started"]

    assert client.post(f"/api/projects/{p['id']}/events", json={"kind": "bogus", "title": "x"}).status_code == 422
    assert client.delete(f"/api/events/{event['id']}").status_code == 204
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert client.delete(f"/api/events/{defaulted['id']}").status_code == 404


def test_missing_project_404(client):
    assert client.get("/api/projects/999").status_code == 404
    assert client.patch("/api/projects/999", json={"notes": "x"}).status_code == 404
    assert client.post("/api/projects/999/events", json={"title": "x"}).status_code == 404


def test_seed_file_loads_once(client, tmp_path):
    assert db.SessionLocal is not None
    with db.SessionLocal() as session:
        assert seed_if_empty(session, tmp_path / "missing.json") == 0
        assert seed_if_empty(session, EXAMPLE_SEED) == 4
        assert seed_if_empty(session, EXAMPLE_SEED) == 0
    projects = client.get("/api/projects").json()
    assert len(projects) == 4
    assert {p["name"] for p in projects if p["overdue"]} == {"The Clockwork Atlas"}
    assert {p["name"] for p in projects if p["needs_action"]} == {"Pocket Synth Mk II"}


def test_bulk_import(client):
    rows = [{"name": "One", "funded_on": "kickstarter"}, {"name": "Two", "funded_on": "backerkit", "original_est": "2027"}]
    res = client.post("/api/import", json=rows)
    assert res.status_code == 201
    assert res.json() == {"imported": 2}
    assert len(client.get("/api/projects").json()) == 2

    # One bad row rejects the whole batch.
    bad = client.post("/api/import", json=[{"name": "Ok", "funded_on": "kickstarter"}, {"name": "Bad", "funded_on": "nope"}])
    assert bad.status_code == 422
    assert len(client.get("/api/projects").json()) == 2
