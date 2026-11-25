"""Poll an IMAP folder for platform email.

The folder is opened read-only (EXAMINE) and messages are fetched with
BODY.PEEK, so nothing is marked read, moved or deleted. Progress is kept as
the folder's UIDVALIDITY plus the last UID processed; Message-IDs dedupe
anything seen twice.

Configuration (environment):
  CROWDTRACKER_IMAP_HOST           required to enable polling
  CROWDTRACKER_IMAP_USER           required
  CROWDTRACKER_IMAP_PASSWORD       or CROWDTRACKER_IMAP_PASSWORD_FILE (e.g. a secret)
  CROWDTRACKER_IMAP_PORT           default 993
  CROWDTRACKER_IMAP_SECURITY       ssl (default) | starttls | none
  CROWDTRACKER_IMAP_FOLDER         default INBOX (a Gmail label works, e.g. "crowdfunding")
  CROWDTRACKER_IMAP_INTERVAL       minutes between checks, default 15 (0 = only on demand)
  CROWDTRACKER_IMAP_SINCE_DAYS     how far back the first check looks, default 365
  CROWDTRACKER_IMAP_ALL_SENDERS    "true" to fetch every message in the folder rather than
                                   only those from platform domains (for a folder that also
                                   holds mail you forwarded by hand)
"""

from __future__ import annotations

import imaplib
import logging
import os
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Setting
from .ingest import ingest_raw
from .parse import SENDER_DOMAINS

log = logging.getLogger("crowdtracker.imap")

BATCH = 25


@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    port: int = 993
    security: str = "ssl"
    folder: str = "INBOX"
    interval_minutes: float = 15
    since_days: int = 365
    all_senders: bool = False


def load_config() -> ImapConfig | None:
    env = os.environ
    host = env.get("CROWDTRACKER_IMAP_HOST", "").strip()
    user = env.get("CROWDTRACKER_IMAP_USER", "").strip()
    password = env.get("CROWDTRACKER_IMAP_PASSWORD", "")
    pw_file = env.get("CROWDTRACKER_IMAP_PASSWORD_FILE", "").strip()
    if not password and pw_file:
        try:
            password = Path(pw_file).read_text().strip()
        except OSError as err:
            log.error("Can't read CROWDTRACKER_IMAP_PASSWORD_FILE: %s", err)
    if not (host and user and password):
        return None
    security = env.get("CROWDTRACKER_IMAP_SECURITY", "ssl").strip().lower()
    return ImapConfig(
        host=host,
        user=user,
        password=password,
        port=int(env.get("CROWDTRACKER_IMAP_PORT") or (993 if security == "ssl" else 143)),
        security=security if security in {"ssl", "starttls", "none"} else "ssl",
        folder=env.get("CROWDTRACKER_IMAP_FOLDER", "INBOX").strip() or "INBOX",
        interval_minutes=float(env.get("CROWDTRACKER_IMAP_INTERVAL") or 15),
        since_days=int(env.get("CROWDTRACKER_IMAP_SINCE_DAYS") or 365),
        all_senders=env.get("CROWDTRACKER_IMAP_ALL_SENDERS", "").strip().lower() in {"1", "true", "yes"},
    )


# --- sync state ------------------------------------------------------------------


def _get(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def _set(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


@dataclass
class SyncResult:
    ok: bool
    fetched: int = 0
    matched: int = 0
    unsorted: int = 0
    skipped: int = 0
    duplicate: int = 0
    error: str | None = None
    finished_at: str | None = None


def status(session: Session) -> dict:
    return {
        "last_sync_at": _get(session, "imap.last_sync_at"),
        "last_error": _get(session, "imap.last_error"),
        "last_result": _get(session, "imap.last_result"),
    }


# --- IMAP ------------------------------------------------------------------------


def connect(cfg: ImapConfig) -> imaplib.IMAP4:
    if cfg.security == "ssl":
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=60)
    else:
        conn = imaplib.IMAP4(cfg.host, cfg.port, timeout=60)
        if cfg.security == "starttls":
            conn.starttls()
    conn.login(cfg.user, cfg.password)
    return conn


def _quote_folder(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sender_query() -> str:
    """OR FROM a OR FROM b ... (IMAP's OR takes exactly two keys)."""
    domains = list(SENDER_DOMAINS)
    query = f'FROM "{domains[-1]}"'
    for domain in reversed(domains[:-1]):
        query = f'OR FROM "{domain}" {query}'
    return query


def _search(conn: imaplib.IMAP4, criteria: str) -> list[int]:
    typ, data = conn.uid("SEARCH", None, criteria)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"SEARCH failed: {data!r}")
    return sorted(int(x) for x in (data[0] or b"").split())


def _uidvalidity(conn: imaplib.IMAP4) -> str | None:
    typ, data = conn.response("UIDVALIDITY")
    if data and data[0]:
        return data[0].decode() if isinstance(data[0], bytes) else str(data[0])
    typ, data = conn.status(_quote_folder(conn._crowdtracker_folder), "(UIDVALIDITY)")  # type: ignore[attr-defined]
    m = re.search(rb"UIDVALIDITY (\d+)", data[0] or b"") if typ == "OK" and data else None
    return m.group(1).decode() if m else None


def _fetch(conn: imaplib.IMAP4, uids: list[int]) -> list[tuple[int, bytes]]:
    typ, data = conn.uid("FETCH", ",".join(map(str, uids)), "(UID BODY.PEEK[])")
    if typ != "OK":
        raise imaplib.IMAP4.error(f"FETCH failed: {data!r}")
    out: list[tuple[int, bytes]] = []
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            m = re.search(rb"UID (\d+)", item[0])
            if m:
                out.append((int(m.group(1)), item[1]))
    return sorted(out)


_lock = threading.Lock()


def sync_once(
    session_factory: Callable[[], Session],
    cfg: ImapConfig | None = None,
    connector: Callable[[ImapConfig], imaplib.IMAP4] = connect,
) -> SyncResult:
    """Fetch new platform mail and ingest it. Safe to call from several threads."""
    cfg = cfg or load_config()
    if cfg is None:
        return SyncResult(ok=False, error="IMAP isn't configured")
    if not _lock.acquire(blocking=False):
        return SyncResult(ok=False, error="A check is already running")
    result = SyncResult(ok=True)
    conn = None
    try:
        conn = connector(cfg)
        conn._crowdtracker_folder = cfg.folder  # type: ignore[attr-defined]
        typ, data = conn.select(_quote_folder(cfg.folder), readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Can't open folder {cfg.folder!r}: {data!r}")
        validity = _uidvalidity(conn)

        with session_factory() as session:
            last_uid = _get(session, "imap.last_uid")
            if _get(session, "imap.uidvalidity") != validity or _get(session, "imap.folder") != cfg.folder:
                last_uid = None  # folder changed or was rebuilt: start over (Message-IDs dedupe)

        senders = "" if cfg.all_senders else " " + _sender_query()
        if last_uid is None:
            since = (datetime.now(UTC) - timedelta(days=cfg.since_days)).strftime("%d-%b-%Y")
            uids = _search(conn, f"SINCE {since}{senders}")
        else:
            uids = [u for u in _search(conn, f"UID {int(last_uid) + 1}:*{senders}") if u > int(last_uid)]

        newest = int(last_uid) if last_uid else 0
        for i in range(0, len(uids), BATCH):
            for uid, raw in _fetch(conn, uids[i : i + BATCH]):
                result.fetched += 1
                with session_factory() as session:
                    outcome, _ = ingest_raw(session, raw)
                setattr(result, outcome, getattr(result, outcome) + 1)
                newest = max(newest, uid)
            with session_factory() as session:
                _set(session, "imap.last_uid", str(newest))
                _set(session, "imap.uidvalidity", validity)
                _set(session, "imap.folder", cfg.folder)
                session.commit()
        if not uids:
            with session_factory() as session:
                _set(session, "imap.uidvalidity", validity)
                _set(session, "imap.folder", cfg.folder)
                if last_uid is None:
                    _set(session, "imap.last_uid", "0")
                session.commit()
    except (imaplib.IMAP4.error, OSError, TimeoutError) as err:
        result.ok = False
        result.error = _friendly(err)
        log.warning("IMAP check failed: %s", err)
    finally:
        if conn is not None:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        result.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        with session_factory() as session:
            _set(session, "imap.last_sync_at", result.finished_at)
            _set(session, "imap.last_error", result.error)
            _set(session, "imap.last_result", repr(asdict(result)))
            session.commit()
        _lock.release()
    return result


def _friendly(err: BaseException) -> str:
    text = str(err)
    if isinstance(err, imaplib.IMAP4.error) and re.search(r"auth|login|credentials|password", text, re.I):
        return f"Sign-in to the mail server was refused. Check the user and app password. ({text})"
    if isinstance(err, OSError | TimeoutError):
        return f"Couldn't reach the mail server: {text or type(err).__name__}"
    return text


# --- background poller -----------------------------------------------------------


class Poller:
    def __init__(self, session_factory: Callable[[], Session], cfg: ImapConfig) -> None:
        self.session_factory = session_factory
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.cfg.interval_minutes <= 0:
            return
        self._thread = threading.Thread(target=self._run, name="crowdtracker-imap", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        # Short delay so startup isn't slowed by the first check.
        if self._stop.wait(5):
            return
        while not self._stop.is_set():
            try:
                sync_once(self.session_factory, self.cfg)
            except Exception:  # noqa: BLE001 - never let the poller die
                log.exception("IMAP check crashed")
            self._stop.wait(self.cfg.interval_minutes * 60)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
