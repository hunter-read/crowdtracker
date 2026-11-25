from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app import clock, db, routes
from app.mail import imap
from app.mail.match import match_project, name_terms, url_slugs
from app.mail.parse import classify, expand_links, parse_message, summary
from app.main import create_app

TODAY = date(2026, 11, 25)

CROWSWORN = "https://www.kickstarter.com/projects/mongooserodeo/crowsworn-a-dark-and-mysterious-action-packed-metroidvania"
CROWS = "https://www.backerkit.com/c/projects/mcdm-productions/crows-fortune-or-death"


def mail(
    *,
    sender: str = "BackerKit <no-reply@backerkit.com>",
    subject: str = "Hello",
    text: str | None = "Hi Hunter,\nSomething happened.",
    html: str | None = None,
    message_id: str | None = "<abc@example.com>",
    when: datetime = datetime(2026, 11, 24, 23, 30, tzinfo=UTC),
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "me@example.com"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(when)
    if message_id:
        msg["Message-ID"] = message_id
    if text is not None:
        msg.set_content(text)
    if html is not None:
        if text is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


@pytest.fixture
def client(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.engine = engine
    db.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    from app import models  # noqa: F401

    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(routes, "_today", lambda: TODAY)
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setenv("CROWDTRACKER_TZ", "America/Los_Angeles")
    for key in ("HOST", "USER", "PASSWORD", "PASSWORD_FILE"):
        monkeypatch.delenv(f"CROWDTRACKER_IMAP_{key}", raising=False)
    with TestClient(create_app()) as c:
        yield c
    db.Base.metadata.drop_all(engine)
    db.engine = None
    db.SessionLocal = None


def make(client, **fields):
    body = {"name": "Test", "funded_on": "kickstarter"} | fields
    r = client.post("/api/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, raw: bytes):
    return client.post("/api/inbox/upload", content=raw, headers={"Content-Type": "message/rfc822"})


# --- parsing -----------------------------------------------------------------------


def test_personal_mail_is_never_kept(client):
    raw = mail(sender="Mom <mom@example.com>", subject="Dinner Sunday?")
    assert parse_message(raw) is None
    r = upload(client, raw)
    assert r.status_code == 422
    assert client.get("/api/inbox/status").json()["total"] == 0


def test_tracked_links_are_unwrapped():
    wrapped = "https://click.e.kickstarter.com/?qs=abc&u=https%3A%2F%2Fwww.kickstarter.com%2Fprojects%2Fmongooserodeo%2Fcrowsworn%2Fposts%2F4512345"
    links = expand_links([wrapped])
    assert "https://www.kickstarter.com/projects/mongooserodeo/crowsworn/posts/4512345" in links


def test_kickstarter_update_email():
    html = f"""<html><body><p>Hi Hunter,</p><p>Crowsworn by Mongoose Rodeo posted an update.</p>
    <a href="https://click.e.kickstarter.com/?u={CROWSWORN.replace(':', '%3A').replace('/', '%2F')}%2Fposts%2F4512345">Read the update</a>
    <p>The demo is out and the full game is on track.</p>
    <a href="https://www.kickstarter.com/settings/notifications">Unsubscribe</a></body></html>"""
    p = parse_message(mail(sender="Kickstarter <no-reply@kickstarter.com>", subject="Project Update #45: New demo", text=None, html=html))
    assert p is not None
    assert (p.platform, p.kind, p.stage_hint) == ("kickstarter", "update", None)
    assert p.url == CROWSWORN.replace("https://", "https://") + "/posts/4512345"
    assert p.campaign_url == CROWSWORN


@pytest.mark.parametrize(
    ("subject", "kind", "stage"),
    [
        ("Your survey for Crows is ready", "survey", "survey_open"),
        ("Reminder: complete your backer survey", "survey", "survey_open"),
        ("We received your order", "survey", "survey_done"),
        ("Your card was successfully charged €90.00", "charge", "charged"),
        ("Payment failed for your pledge", "charge", None),
        ("Your address has been locked", "address_lock", "address_locked"),
        ("Addresses lock tomorrow!", "address_lock", None),
        ("Your order has shipped!", "shipping", "shipping"),
        ("Your package was delivered", "delivery", None),
        ("Project Update #12: Shipping begins!", "update", None),
        ("Crowsworn was successfully funded!", "update", "funded"),
        ("A quick hello", "note", None),
    ],
)
def test_classify(subject, kind, stage):
    assert classify(subject, "") == (kind, stage)


def test_creator_update_that_mentions_shipping_never_moves_the_stage():
    html = '<p>We have shipped 85% of rewards! Your tracking number will follow.</p><a href="https://www.backerkit.com/c/projects/dragonsteel/hoids-storybook-collection/updates/57335">Read</a>'
    p = parse_message(mail(subject="We're grateful for you, Worldhoppers!", text=None, html=html))
    assert p is not None and p.kind == "update" and p.stage_hint is None


def test_tracking_link_and_forwarded_mail():
    body = (
        "---------- Forwarded message ---------\n"
        "From: Gamefound <notifications@gamefound.com>\n"
        "Subject: Your pledge has been shipped\n\n"
        "Track it here: https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111\n"
    )
    p = parse_message(mail(sender="Me <me@gmail.com>", subject="Fwd: Your pledge has been shipped", text=body))
    assert p is not None
    assert p.platform == "gamefound"
    assert p.subject == "Your pledge has been shipped"
    assert p.kind == "shipping" and p.stage_hint == "shipping"
    assert p.tracking_url.startswith("https://tools.usps.com/")


def test_missing_message_id_uses_a_hash():
    raw = mail(message_id=None)
    p1, p2 = parse_message(raw), parse_message(raw)
    assert p1.message_id == p2.message_id and p1.message_id.startswith("sha256:")


def test_summary_skips_greetings():
    assert summary("Hi Hunter,\n\nView this email in your browser\nThe books ship in January.") == "The books ship in January."


# --- matching ----------------------------------------------------------------------


class P:
    def __init__(self, id, name, campaign_url=None, pledge_manager_url=None, match_terms=None):
        self.id, self.name, self.campaign_url, self.pledge_manager_url, self.match_terms = (
            id,
            name,
            campaign_url,
            pledge_manager_url,
            match_terms,
        )


def test_url_slugs():
    assert url_slugs(CROWSWORN) == {"crowsworn-a-dark-and-mysterious-action-packed-metroidvania"}
    assert url_slugs("https://crows-fortune-or-death.backerkit.com/backer/review") == {"crows-fortune-or-death"}
    assert url_slugs("https://www.backerkit.com/c/projects/mcdm-productions/crows-fortune-or-death/updates/1") == {
        "crows-fortune-or-death"
    }
    assert url_slugs("https://gamefound.com/en/projects/unstable-games/here-to-slay-dungeons/updates/47") == {
        "here-to-slay-dungeons"
    }
    assert url_slugs("https://www.backerkit.com/c/users/active_projects") == set()


def test_names_match_whole_words_only():
    projects = [P(1, "Crowsworn", CROWSWORN), P(2, "Crows: Fortune or Death", CROWS)]
    m = match_project("Your survey for Crows: Fortune or Death is ready", "", [], projects)
    assert m and m.project_id == 2
    m = match_project("Crowsworn: new demo", "", [], projects)
    assert m and m.project_id == 1
    # "Crows" alone is a name part of project 2, never a prefix of Crowsworn.
    m = match_project("Crows playtest is live", "", [], projects)
    assert m and m.project_id == 2


def test_links_beat_names():
    projects = [P(1, "Crowsworn", CROWSWORN), P(2, "Crows: Fortune or Death", CROWS)]
    m = match_project("New update", "Crows: Fortune or Death fans will love this", [CROWSWORN + "/posts/9"], projects)
    assert m and m.project_id == 1 and m.reason == "campaign link"


def test_ties_go_to_the_tray():
    projects = [P(1, "Twilight Sword"), P(2, "Twilight Sword: Monster Book")]
    assert match_project("Twilight Sword: Monster Book is live", "", [], projects).project_id == 2
    assert match_project("A Twilight Sword shipping note", "", [], projects) is None


def test_match_terms_and_generic_words():
    dcc = P(1, "Dungeon Crawler Carl RPG + Unstoppable", match_terms="CarlRPG, DCC RPG")
    other = P(2, "Absurdia: The (Meta)Physical Edition")
    assert "carlrpg" in name_terms(dcc)
    assert match_project("CarlRPG PDF codes are here", "", [], [dcc, other]).project_id == 1
    # Generic name parts like "Edition" never match on their own.
    assert match_project("Deluxe Edition preview", "", [], [dcc, other]) is None


# --- ingest and API ----------------------------------------------------------------


def test_matched_email_becomes_event_and_moves_stage(client):
    crows = make(client, name="Crows: Fortune or Death", funded_on="backerkit", campaign_url=CROWS, stage="funded")
    make(client, name="Crowsworn", campaign_url=CROWSWORN, stage="funded")
    r = upload(client, mail(subject="Your survey for Crows: Fortune or Death is ready", text="Hi Hunter,\nFill it in by Sep 29."))
    assert r.status_code == 201, r.text
    assert r.json()["outcome"] == "matched"
    detail = client.get(f"/api/projects/{crows['id']}").json()
    assert detail["stage"] == "survey_open"
    email_events = [e for e in detail["events"] if e["source"] == "email"]
    assert len(email_events) == 1
    ev = email_events[0]
    # 23:30 UTC on Nov 24 is still Nov 24 in Los Angeles.
    assert (ev["kind"], ev["occurred_on"], ev["body"]) == ("survey", "2026-11-24", "Fill it in by Sep 29.")
    assert any(e["title"] == "Stage: funded → survey_open (from email)" for e in detail["events"])


def test_stage_never_moves_backwards_or_past_arrivals(client):
    p = make(client, name="Hoid's Storybook Collection", stage="shipping")
    upload(client, mail(subject="Hoid's Storybook Collection: your survey is ready", message_id="<1@x>"))
    assert client.get(f"/api/projects/{p['id']}").json()["stage"] == "shipping"

    q = make(
        client,
        name="Draw Steel: Crack the Sun",
        rewards=[{"name": "PDF", "kind": "digital", "received_on": "2026-09-15"}, {"name": "Book", "kind": "physical"}],
    )
    assert client.get(f"/api/projects/{q['id']}").json()["stage"] == "partial"
    upload(client, mail(subject="Draw Steel: Crack the Sun - your order has shipped", message_id="<2@x>"))
    assert client.get(f"/api/projects/{q['id']}").json()["stage"] == "partial"


def test_tracking_url_is_the_event_link(client):
    p = make(client, name="Here to Slay DUNGEONS", funded_on="gamefound", stage="address_locked")
    upload(
        client,
        mail(
            sender="Gamefound <notifications@gamefound.com>",
            subject="Here to Slay DUNGEONS: your pledge has been shipped",
            text="Track it: https://www.fedex.com/fedextrack/?trknbr=123",
        ),
    )
    detail = client.get(f"/api/projects/{p['id']}").json()
    ev = next(e for e in detail["events"] if e["source"] == "email")
    assert ev["kind"] == "shipping" and ev["url"].startswith("https://www.fedex.com/")
    assert detail["stage"] == "shipping"


def test_unsorted_tray_assign_ignore_and_duplicates(client):
    a = make(client, name="Twilight Sword")
    b = make(client, name="Twilight Sword: Monster Book", stage="live")
    raw = mail(subject="Twilight Sword news", message_id="<tie@x>")
    assert upload(client, raw).json()["outcome"] == "unsorted"
    assert upload(client, raw).json()["outcome"] == "duplicate"
    assert client.get("/api/summary").json()["unsorted"] == 1

    tray = client.get("/api/inbox").json()
    assert len(tray) == 1 and tray[0]["status"] == "unsorted"
    msg_id = tray[0]["id"]

    r = client.post(f"/api/inbox/{msg_id}/assign", json={"project_id": b["id"]})
    assert r.status_code == 200 and r.json()["project_name"] == "Twilight Sword: Monster Book"
    assert client.get("/api/inbox").json() == []
    assert any(e["source"] == "email" for e in client.get(f"/api/projects/{b['id']}").json()["events"])

    # Reassigning moves the event rather than copying it.
    client.post(f"/api/inbox/{msg_id}/assign", json={"project_id": a["id"]})
    assert not any(e["source"] == "email" for e in client.get(f"/api/projects/{b['id']}").json()["events"])
    assert any(e["source"] == "email" for e in client.get(f"/api/projects/{a['id']}").json()["events"])

    r = client.post(f"/api/inbox/{msg_id}/ignore")
    assert r.json()["status"] == "ignored"
    assert not any(e["source"] == "email" for e in client.get(f"/api/projects/{a['id']}").json()["events"])
    assert client.post(f"/api/inbox/{msg_id}/unsort").json()["status"] == "unsorted"


def test_deleting_a_pledge_returns_its_mail_to_the_tray(client):
    p = make(client, name="Voidheart Symphony")
    upload(client, mail(subject="Voidheart Symphony: final PDFs"))
    assert client.get("/api/inbox?status=matched").json()[0]["project_id"] == p["id"]
    client.delete(f"/api/projects/{p['id']}")
    tray = client.get("/api/inbox").json()
    assert len(tray) == 1 and tray[0]["project_id"] is None


def test_match_terms_round_trip(client):
    p = make(client, name="Dungeon Crawler Carl RPG + Unstoppable", match_terms="CarlRPG")
    assert p["match_terms"] == "CarlRPG"
    r = client.patch(f"/api/projects/{p['id']}", json={"match_terms": "CarlRPG, Princess Donut"})
    assert r.json()["match_terms"] == "CarlRPG, Princess Donut"


def test_sync_needs_configuration(client):
    assert client.get("/api/inbox/status").json()["configured"] is False
    assert client.post("/api/inbox/sync").status_code == 409


# --- IMAP --------------------------------------------------------------------------


class FakeImap:
    """Just enough of imaplib.IMAP4 for sync_once."""

    def __init__(self, messages: dict[int, bytes], validity: str = "42"):
        self.messages = messages
        self.validity = validity
        self.searches: list[str] = []
        self.readonly = None
        self.flags_changed = False

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def response(self, code):
        return code, [self.validity.encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[1]
            self.searches.append(criteria)
            uids = sorted(self.messages)
            if criteria.startswith("UID "):
                lo = int(criteria.split()[1].split(":")[0])
                uids = [u for u in uids if u >= lo] or uids[-1:]
            return "OK", [" ".join(map(str, uids)).encode()]
        if command == "FETCH":
            assert "PEEK" in args[1]
            out = []
            for u in map(int, args[0].split(",")):
                out.append((f"{u} (UID {u} BODY[] {{1}}".encode(), self.messages[u]))
                out.append(b")")
            return "OK", out
        if command == "STORE":
            self.flags_changed = True
        raise AssertionError(command)

    def logout(self):
        return "BYE", []


def test_imap_sync(client):
    make(client, name="Crows: Fortune or Death", campaign_url=CROWS)
    messages = {
        10: mail(subject="Crows: Fortune or Death - your survey is ready", message_id="<a@x>"),
        11: mail(sender="Friend <f@example.com>", subject="lunch", message_id="<b@x>"),
        12: mail(subject="Something else entirely", message_id="<c@x>"),
    }
    fake = FakeImap(messages)
    cfg = imap.ImapConfig(host="imap.example.com", user="me", password="pw", folder="crowdfunding")
    r = imap.sync_once(db.SessionLocal, cfg, connector=lambda _c: fake)
    assert r.ok, r.error
    assert (r.fetched, r.matched, r.unsorted, r.skipped) == (3, 1, 1, 1)
    assert fake.readonly is True and not fake.flags_changed
    assert "SINCE" in fake.searches[0] and 'FROM "kickstarter.com"' in fake.searches[0]

    # Next run only asks for newer UIDs, and nothing new means nothing fetched.
    r = imap.sync_once(db.SessionLocal, cfg, connector=lambda _c: fake)
    assert r.fetched == 0 and fake.searches[-1].startswith("UID 13:*")

    messages[13] = mail(subject="Crows: Fortune or Death - your order has shipped", message_id="<d@x>")
    r = imap.sync_once(db.SessionLocal, cfg, connector=lambda _c: fake)
    assert (r.fetched, r.matched) == (1, 1)

    # A rebuilt folder (new UIDVALIDITY) is re-read, and Message-IDs stop duplicates.
    fake.validity = "43"
    r = imap.sync_once(db.SessionLocal, cfg, connector=lambda _c: fake)
    assert r.duplicate == 3 and r.matched == 0

    status = client.get("/api/inbox/status").json()
    assert status["last_error"] is None and status["total"] == 3


def test_imap_errors_are_recorded(client):
    import imaplib

    def refuse(_cfg):
        raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    cfg = imap.ImapConfig(host="imap.example.com", user="me", password="bad")
    r = imap.sync_once(db.SessionLocal, cfg, connector=refuse)
    assert not r.ok and "app password" in r.error
    assert "app password" in client.get("/api/inbox/status").json()["last_error"]


def test_password_file(tmp_path, monkeypatch):
    secret = tmp_path / "pw"
    secret.write_text("s3cret\n")
    monkeypatch.setenv("CROWDTRACKER_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("CROWDTRACKER_IMAP_USER", "me@gmail.com")
    monkeypatch.delenv("CROWDTRACKER_IMAP_PASSWORD", raising=False)
    monkeypatch.setenv("CROWDTRACKER_IMAP_PASSWORD_FILE", str(secret))
    monkeypatch.setenv("CROWDTRACKER_IMAP_FOLDER", "crowdfunding")
    cfg = imap.load_config()
    assert cfg and cfg.password == "s3cret" and cfg.folder == "crowdfunding" and cfg.port == 993
