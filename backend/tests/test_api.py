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
    assert summary == {
        "total": 5, "open": 4, "overdue": 1, "needs_action": 1, "partial": 0, "delivered": 1, "cancelled": 0
    }
    assert [p["name"] for p in client.get("/api/projects?view=received").json()] == ["Done"]
    assert client.get("/api/projects?view=cancelled").json() == []


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
    lanterns = next(p for p in projects if p["name"] == "Lanterns of the Deep")
    assert lanterns["stage"] == "partial"
    assert lanterns["rewards_received"] == 1


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


def test_campaign_ended(client):
    p = make(client, campaign_ended="2021-08-10", original_est="2023-12")
    assert p["campaign_ended"] == "2021-08-10"
    assert p["months_since_campaign"] == 63
    cleared = client.patch(f"/api/projects/{p['id']}", json={"campaign_ended": None}).json()
    assert cleared["campaign_ended"] is None
    assert cleared["months_since_campaign"] is None
    assert client.post("/api/projects", json={"name": "X", "campaign_ended": "August 2021"}).status_code == 422


def test_existing_database_gets_new_columns(tmp_path):
    """A database created before campaign_ended existed is upgraded in place."""
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, category VARCHAR(60),"
        " creator VARCHAR(200), funded_on VARCHAR(30) NOT NULL, pledge_manager VARCHAR(30),"
        " campaign_url VARCHAR(500), pledge_manager_url VARCHAR(500), tier VARCHAR(200), pledge_amount FLOAT,"
        " currency VARCHAR(3) NOT NULL, original_est VARCHAR(10), current_est VARCHAR(10),"
        " stage VARCHAR(30) NOT NULL, notes TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
    )
    con.execute(
        "INSERT INTO projects (name, funded_on, currency, stage, created_at, updated_at)"
        " VALUES ('Old', 'kickstarter', 'USD', 'funded', '2026-01-01', '2026-01-01')"
    )
    con.commit()
    con.close()

    db.init_db(f"sqlite:///{path}")
    try:
        con = sqlite3.connect(path)
        cols = {row[1] for row in con.execute("PRAGMA table_info(projects)")}
        assert {"campaign_ended", "received_on"} <= cols
        assert con.execute("SELECT name FROM sqlite_master WHERE name='rewards'").fetchone()
        db.init_db(f"sqlite:///{path}")  # running again is a no-op
    finally:
        db.engine = None
        db.SessionLocal = None


def test_mark_received_whole(client):
    p = make(client, original_est="2025-12")
    body = client.patch(f"/api/projects/{p['id']}", json={"stage": "delivered"}).json()
    assert body["received_on"] == TODAY.isoformat()
    assert body["months_late"] == 11
    assert body["overdue"] is False
    assert [(e["kind"], e["title"]) for e in body["events"]] == [("delivery", "Received")]

    q = make(client, name="On time", original_est="2027")
    body = client.patch(f"/api/projects/{q['id']}", json={"stage": "delivered", "received_on": "2026-06-01"}).json()
    assert body["received_on"] == "2026-06-01"
    assert body["months_late"] == 0
    assert body["events"][0]["occurred_on"] == "2026-06-01"

    # Reopening clears the received date.
    reopened = client.patch(f"/api/projects/{q['id']}", json={"stage": "shipping"}).json()
    assert reopened["received_on"] is None


def add_reward(client, pid, **body):
    res = client.post(f"/api/projects/{pid}/rewards", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_rewards_arrive_in_stages(client):
    p = make(client, original_est="2026-06", stage="shipping")
    add_reward(client, p["id"], name="Rulebook PDF", kind="digital")
    add_reward(client, p["id"], name="Hardcover", kind="physical")
    body = add_reward(client, p["id"], name="Wave 2 add-ons", kind="physical")
    assert [r["name"] for r in body["rewards"]] == ["Rulebook PDF", "Hardcover", "Wave 2 add-ons"]
    assert body["rewards_received"] == 0
    pdf, hc, wave2 = (r["id"] for r in body["rewards"])

    body = client.patch(f"/api/rewards/{pdf}", json={"received_on": "2026-08-01"}).json()
    assert body["stage"] == "partial"
    assert body["rewards_received"] == 1
    assert body["overdue"] is True  # the rest is still late
    assert client.get("/api/summary").json()["partial"] == 1
    assert [p["id"] for p in client.get("/api/projects?view=partial").json()] == [p["id"]]

    client.patch(f"/api/rewards/{hc}", json={"received_on": "2026-10-02"})
    body = client.patch(f"/api/rewards/{wave2}", json={"received_on": "2026-11-20"}).json()
    assert body["stage"] == "delivered"
    assert body["received_on"] == "2026-11-20"
    assert body["months_late"] == 5
    titles = [e["title"] for e in body["events"]]
    assert "Received: Rulebook PDF" in titles and "Received: Wave 2 add-ons" in titles
    assert "Stage: partial → delivered (all rewards received)" in titles

    # Un-receiving one puts it back to partial.
    body = client.patch(f"/api/rewards/{wave2}", json={"received_on": None}).json()
    assert body["stage"] == "partial"
    assert body["received_on"] is None

    # Deleting the outstanding one completes it.
    res = client.delete(f"/api/rewards/{wave2}")
    assert res.status_code == 200
    assert res.json()["stage"] == "delivered"
    assert res.json()["received_on"] == "2026-10-02"


def test_mark_received_fills_rewards(client):
    p = make(client)
    add_reward(client, p["id"], name="Game key", kind="digital", received_on="2026-01-05")
    body = add_reward(client, p["id"], name="Steelbook", kind="physical")
    assert body["stage"] == "partial"
    body = client.patch(f"/api/projects/{p['id']}", json={"stage": "delivered"}).json()
    assert [r["received_on"] for r in body["rewards"]] == ["2026-01-05", TODAY.isoformat()]
    assert body["received_on"] == TODAY.isoformat()


def test_import_with_rewards_and_validation(client):
    rows = [
        {"name": "Both", "funded_on": "kickstarter", "rewards": [
            {"name": "PDF", "kind": "digital", "received_on": "2026-02-01"},
            {"name": "Print", "kind": "physical"},
        ]},
        {"name": "Done", "funded_on": "backerkit", "rewards": [{"name": "Box", "received_on": "2026-03-01"}]},
    ]
    assert client.post("/api/import", json=rows).status_code == 201
    by = {p["name"]: p for p in client.get("/api/projects").json()}
    assert by["Both"]["stage"] == "partial"
    assert by["Done"]["stage"] == "delivered" and by["Done"]["received_on"] == "2026-03-01"

    pid = by["Both"]["id"]
    assert client.post(f"/api/projects/{pid}/rewards", json={"name": "X", "kind": "vinyl"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/rewards", json={"name": ""}).status_code == 422
    assert client.patch("/api/rewards/999", json={"name": "x"}).status_code == 404
    rid = by["Both"]["rewards"][0]["id"]
    assert client.patch(f"/api/rewards/{rid}", json={"name": None}).status_code == 422


def test_cancelled_ignores_rewards(client):
    p = make(client, stage="cancelled")
    rid = add_reward(client, p["id"], name="Refund?")["rewards"][0]["id"]
    body = client.patch(f"/api/rewards/{rid}", json={"received_on": "2026-01-01"}).json()
    assert body["stage"] == "cancelled"
