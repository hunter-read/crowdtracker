"""Turn a raw platform email into the few facts crowdtracker needs.

Nothing here touches the database. `parse_message` returns None for mail that
isn't from a crowdfunding platform, so personal mail is never stored.
"""

from __future__ import annotations

import email
import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

# Sender domain suffix -> platform. Subdomains count (mail.backerkit.com,
# campaign.backerkit.com, e.kickstarter.com, ...).
SENDER_DOMAINS: dict[str, str] = {
    "kickstarter.com": "kickstarter",
    "backerkit.com": "backerkit",
    "gamefound.com": "gamefound",
    "pledgemanager.com": "pledgemanager",
    "pledgebox.com": "pledgebox",
    "indiegogo.com": "indiegogo",
}

# Hosts of the pages emails link to, for working out which pledge an email is about.
PLATFORM_HOSTS = SENDER_DOMAINS

CARRIER_HOSTS = (
    "usps.com",
    "ups.com",
    "fedex.com",
    "dhl.com",
    "dhl.de",
    "canadapost-postescanada.ca",
    "canadapost.ca",
    "royalmail.com",
    "parcelforce.com",
    "auspost.com.au",
    "postnl.nl",
    "aftership.com",
    "parcelsapp.com",
    "17track.net",
    "easyship.com",
    "trackmyshipment.co",
    "uniuni.com",
    "omniparcel.com",
    "osmworldwide.com",
    "ontrac.com",
    "lasership.com",
    "gls-group.eu",
    "dpd.com",
    "evri.com",
)

MAX_EXCERPT = 2000


@dataclass
class ParsedMail:
    message_id: str
    received_at: datetime
    sender: str
    platform: str
    subject: str
    text: str
    links: list[str] = field(default_factory=list)
    kind: str = "note"
    stage_hint: str | None = None
    url: str | None = None
    tracking_url: str | None = None
    campaign_url: str | None = None

    @property
    def excerpt(self) -> str:
        return self.text[:MAX_EXCERPT]


# --- text extraction -------------------------------------------------------------


class _HTMLText(HTMLParser):
    """HTML to readable text, keeping link targets."""

    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "blockquote"}
    _SKIP = {"style", "script", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _clean(text: str) -> str:
    text = text.replace("\r", "").replace("‌", "").replace(" ", " ").replace("͏", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _body(msg: EmailMessage) -> tuple[str, list[str]]:
    """Readable text and every link in the message."""
    plain = msg.get_body(preferencelist=("plain",))
    rich = msg.get_body(preferencelist=("html",))
    links: list[str] = []
    text = ""
    if rich is not None:
        parser = _HTMLText()
        parser.feed(rich.get_content())
        links.extend(parser.links)
        text = "".join(parser.parts)
    if plain is not None:
        plain_text = plain.get_content()
        links.extend(re.findall(r"https?://[^\s<>\")\]]+", plain_text))
        # The plain part is usually tidier; prefer it when it has substance.
        if len(plain_text.strip()) > 80 or not text.strip():
            text = plain_text
    return _clean(html.unescape(text)), links


def expand_links(links: list[str]) -> list[str]:
    """Links plus any URLs wrapped inside click-tracking redirects."""
    out: list[str] = []
    for link in links:
        link = link.strip()
        if not link.lower().startswith(("http://", "https://")):
            continue
        out.append(link)
        decoded = link
        for _ in range(3):  # redirects can be encoded more than once
            nxt = unquote(decoded)
            if nxt == decoded:
                break
            decoded = nxt
            out.extend(re.findall(r"https?://[^\s&\"'<>]+", decoded[8:]))
    seen: set[str] = set()
    unique = []
    for link in out:
        link = link.rstrip(".,);")
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _domain_platform(host: str, table: dict[str, str]) -> str | None:
    for suffix, platform in table.items():
        if host == suffix or host.endswith("." + suffix):
            return platform
    return None


# --- classification --------------------------------------------------------------

_UPDATE = re.compile(
    r"(\b(project )?update\s*#\s*\d+|\bposted an? (new )?update\b|\bnew (project )?update\b|^\s*update:)",
    re.I,
)

# Personal, transactional notices. Order matters: the first rule that matches wins.
# Each: (kind, stage the pledge has reached or None, pattern)
_RULES: list[tuple[str, str | None, re.Pattern[str]]] = [
    ("delivery", None, re.compile(r"\b(has been|was) delivered\b|\bdelivered to\b|\bdelivery (confirmed|complete)", re.I)),
    (
        "shipping",
        "shipping",
        re.compile(
            r"\b(has|have) (been )?shipped\b|\border (has )?shipped\b|\bon (its|their) way\b|\btracking (number|info|information|link)\b|\bout for delivery\b|\bshipment (is )?(on|in transit)|\byour (order|package|reward|pledge)s? (has |have )?(been )?(sent|dispatched)",
            re.I,
        ),
    ),
    (
        "address_lock",
        "address_locked",
        re.compile(
            r"\b(your )?address(es)? (has|have) been locked\b|\baddress(es)? (is|are) (now )?locked\b|\bwe('ve| have) locked (your )?address",
            re.I,
        ),
    ),
    ("address_lock", None, re.compile(r"\baddress(es)? (will )?lock|\block(ing)? (your |all )?address|\baddress lock", re.I)),
    (
        "charge",
        None,
        re.compile(r"\bpayment (failed|declined|unsuccessful)\b|\b(card|payment) (was )?declined\b|\bupdate your payment", re.I),
    ),
    (
        "charge",
        "charged",
        re.compile(
            r"\b(card|account) (has been |was )?(successfully )?charged\b|\byou('ve| have)? (been|were) charged\b|\bpayment (received|successful|confirmed|collected|complete)\b|\bpledge (was |has been )?collected\b|\breceipt\b|\bthanks for your payment\b",
            re.I,
        ),
    ),
    (
        "survey",
        "survey_done",
        re.compile(
            r"\bsurvey (is )?(complete|completed|submitted|received)\b|\bthanks? (you )?for (completing|filling out) (your |the )?survey|\bwe('ve| have)? received your (order|survey)|\border confirmation\b",
            re.I,
        ),
    ),
    (
        "survey",
        "survey_open",
        re.compile(
            r"\b(complete|fill out|take|answer|finish) (your|the) (backer )?survey\b|\bsurvey (is )?(now )?(ready|available|open|waiting)\b|\byour (backer )?survey\b|\bpledge manager (is )?(now )?(open|live)\b|\bconfirm your (pledge|order|reward)s?\b|\breminder:? .*survey\b",
            re.I,
        ),
    ),
    ("survey", None, re.compile(r"\bsurvey\b|\bpledge manager\b", re.I)),
    (
        "update",
        "funded",
        re.compile(r"\b(was |has been |is )?successfully funded\b|\bproject (was |has been )?funded\b|\bit'?s funded\b", re.I),
    ),
]


def classify(subject: str, text: str) -> tuple[str, str | None]:
    """(event kind, stage hint).

    Creator updates are broadcasts: they never move the stage, even when they
    talk about shipping. Only personal notices (your survey, your card, your
    package) carry a stage hint.
    """
    head = text[:1500]
    if _UPDATE.search(subject) or re.match(r"\s*(project )?update\s*#\s*\d+", head, re.I):
        return "update", None
    for kind, stage, pattern in _RULES:
        if pattern.search(subject):
            return kind, stage
    for kind, stage, pattern in _RULES:
        # The body alone is weaker evidence: keep the kind, drop most stage hints.
        if pattern.search(head):
            keep = stage if stage in {"shipping", "survey_open"} and kind in {"shipping", "survey"} else None
            return kind, keep
    return "note", None


# --- links of interest -----------------------------------------------------------

_POST_PATTERNS = (
    re.compile(r"kickstarter\.com/projects/[^/]+/[^/?#]+/posts/\d+", re.I),
    re.compile(r"backerkit\.com/c/projects/[^/]+/[^/?#]+/updates/\d+", re.I),
    re.compile(r"gamefound\.com/[a-z]{2}/projects/[^/]+/[^/?#]+/updates/\d+", re.I),
    re.compile(r"indiegogo\.com/projects/[^/?#]+(/x/\d+)?#?/updates", re.I),
)

_CAMPAIGN_PATTERNS = (
    re.compile(r"https?://(www\.)?kickstarter\.com/projects/[^/?#\s]+/[^/?#\s]+", re.I),
    re.compile(r"https?://(www\.)?backerkit\.com/c/projects/[^/?#\s]+/[^/?#\s]+", re.I),
    re.compile(r"https?://(www\.)?gamefound\.com/[a-z]{2}/projects/[^/?#\s]+/[^/?#\s]+", re.I),
    re.compile(r"https?://(www\.)?indiegogo\.com/projects/[^/?#\s]+", re.I),
)

_JUNK_LINK = re.compile(r"unsubscribe|preferences|/settings|privacy|terms|help\.|support\.|/faq|facebook|twitter|instagram|discord|youtube|tiktok", re.I)


def _first(links: list[str], patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for link in links:
        for pattern in patterns:
            m = pattern.search(link)
            if m:
                found = m.group(0)
                if found.lower().startswith("http"):
                    return found
                # Keep the scheme and subdomain (www.) the link actually had.
                prefix = link[: m.start()]
                if re.fullmatch(r"https?://([\w-]+\.)*", prefix, re.I):
                    return link[: m.end()]
                return "https://" + found.lstrip("/")
    return None


def _tracking(links: list[str]) -> str | None:
    for link in links:
        host = _host(link)
        if any(host == c or host.endswith("." + c) for c in CARRIER_HOSTS):
            return link
    return None


def _best_link(links: list[str], platform_hosts: dict[str, str]) -> str | None:
    """The most useful platform link in the email (post > survey page > anything)."""
    post = _first(links, _POST_PATTERNS)
    if post:
        return post
    for link in links:
        host = _host(link)
        if _domain_platform(host, platform_hosts) and not _JUNK_LINK.search(link) and "/backer" in link:
            return link
    return None


# --- forwarded mail --------------------------------------------------------------

_FWD_FROM = re.compile(r"^\s*From:\s*(.+)$", re.I | re.M)


def _forwarded_sender(text: str) -> str | None:
    """For a manually forwarded email, the original From line's address."""
    if not re.search(r"forwarded message|begin forwarded message|^-+\s*original message", text, re.I | re.M):
        return None
    for m in _FWD_FROM.finditer(text[:4000]):
        _, addr = parseaddr(m.group(1).strip())
        if addr and _domain_platform(addr.rsplit("@", 1)[-1].lower(), SENDER_DOMAINS):
            return addr
    return None


def _strip_fwd_prefix(subject: str) -> str:
    return re.sub(r"^\s*((fwd?|fw|re)\s*:\s*)+", "", subject, flags=re.I).strip()


# --- entry point -----------------------------------------------------------------


def parse_message(raw: bytes) -> ParsedMail | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)

    name, addr = parseaddr(str(msg.get("From", "")))
    addr = addr.lower()
    text, links = _body(msg)
    platform = _domain_platform(addr.rsplit("@", 1)[-1], SENDER_DOMAINS) if "@" in addr else None
    if platform is None:
        # Reply-To / Sender sometimes carry the platform when a mail service sends it.
        for header in ("Sender", "Reply-To", "Return-Path"):
            _, other = parseaddr(str(msg.get(header, "")))
            p = _domain_platform(other.lower().rsplit("@", 1)[-1], SENDER_DOMAINS) if "@" in other else None
            if p:
                platform = p
                break
    if platform is None:
        fwd = _forwarded_sender(text)
        if fwd:
            addr = fwd.lower()
            name = ""
            platform = _domain_platform(addr.rsplit("@", 1)[-1], SENDER_DOMAINS)
    if platform is None:
        return None

    subject = _strip_fwd_prefix(str(msg.get("Subject", "")).strip()) or "(no subject)"
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
    except (TypeError, ValueError):
        received = None
    if received is None:
        received = datetime.now(UTC)
    elif received.tzinfo is None:
        received = received.replace(tzinfo=UTC)

    message_id = str(msg.get("Message-ID", "")).strip()
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()

    all_links = expand_links(links)
    kind, stage = classify(subject, text)
    if kind != "update" and _first(all_links, _POST_PATTERNS):
        # Links to a creator post: this is a broadcast update, whatever it says.
        kind, stage = "update", None
    sender = f"{name} <{addr}>" if name else addr

    return ParsedMail(
        message_id=message_id[:500],
        received_at=received,
        sender=sender[:300],
        platform=platform,
        subject=subject[:500],
        text=text,
        links=all_links,
        kind=kind,
        stage_hint=stage,
        url=_best_link(all_links, PLATFORM_HOSTS),
        tracking_url=_tracking(all_links),
        campaign_url=_first(all_links, _CAMPAIGN_PATTERNS),
    )


_BOILERPLATE = re.compile(
    r"^(hi|hello|hey|dear|greetings)\b.{0,40}[,!]?$|view (this|in) (email|browser)|view online|^view update$|^read more$|^\W*$",
    re.I,
)


def summary(text: str, limit: int = 400) -> str | None:
    """A short excerpt for the timeline, skipping greetings, bare links and header junk."""
    text = re.sub(r"https?://\S+", "", text)
    lines = [ln for ln in text.split("\n") if ln.strip() and not _BOILERPLATE.search(ln.strip())]
    out = ""
    for line in lines:
        if len(out) + len(line) + 1 > limit:
            if not out:
                cut = line[:limit]
                out = cut[: cut.rfind(" ")] + "…" if " " in cut else cut
            else:
                out += " …"
            break
        out = f"{out} {line}".strip()
    return out or None
