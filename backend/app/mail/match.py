"""Work out which pledge an email is about.

Two kinds of evidence, strongest first:

1. A campaign or pledge-manager link in the email whose project slug matches a
   pledge's saved URLs.
2. The pledge's name (or one of its parts, or its match terms) appearing as
   whole words in the subject or near the top of the body.

Names are matched on word boundaries, so "Crows" never matches "Crowsworn".
When two pledges are equally likely the email goes to the unsorted tray
rather than being guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

# Words too generic to identify a pledge on their own.
_GENERIC = {
    "the",
    "and",
    "game",
    "games",
    "book",
    "books",
    "rpg",
    "ttrpg",
    "edition",
    "deluxe",
    "collection",
    "volume",
    "vol",
    "set",
    "box",
    "core",
    "rules",
    "board",
    "card",
    "cards",
    "dice",
    "expansion",
    "kickstarter",
    "backerkit",
    "gamefound",
    "update",
    "project",
    "campaign",
    "limited",
    "hardcover",
    "hardcovers",
    "pdf",
    "supplement",
    "adventure",
    "adventures",
    "new",
}

_SKIP_SUBDOMAINS = {"www", "mail", "email", "e", "help", "support", "campaign", "go", "click", "links", "link", "app", "api", "cdn", "images"}


class Candidate(Protocol):
    id: int
    name: str
    campaign_url: str | None
    pledge_manager_url: str | None
    match_terms: str | None


@dataclass
class Match:
    project_id: int
    reason: str


def normalize(text: str) -> str:
    text = text.casefold().replace("’", "'").replace("&", " and ")
    text = re.sub(r"[^\w]+", " ", text)
    return f" {re.sub(r'\s+', ' ', text).strip()} "


def url_slugs(url: str | None) -> set[str]:
    """Project identifiers in a platform URL (path slug or pledge-manager subdomain)."""
    if not url:
        return set()
    try:
        parts = urlsplit(url if "://" in url else "https://" + url)
    except ValueError:
        return set()
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    out: set[str] = set()
    if "projects" in segs:
        i = segs.index("projects")
        rest = segs[i + 1 :]
        # /projects/<creator>/<slug> (Kickstarter, BackerKit, Gamefound) or /projects/<slug> (Indiegogo)
        if host.endswith("indiegogo.com") and rest:
            out.add(rest[0])
        elif len(rest) >= 2:
            out.add(rest[1])
        elif rest:
            out.add(rest[0])
    labels = host.split(".")
    for platform_domain in ("backerkit.com", "pledgemanager.com", "pledgebox.com", "gamefound.com"):
        if host.endswith("." + platform_domain) and len(labels) >= 3 and labels[0] not in _SKIP_SUBDOMAINS:
            out.add(labels[0])
    return {s.lower() for s in out if len(s) >= 4}


def name_terms(project: Candidate) -> list[str]:
    """Whole-word phrases that identify the pledge, longest first."""
    terms: set[str] = set()
    name = project.name.strip()
    terms.add(name)
    for part in re.split(r"\s*[:–—|(),]\s*|\s+-\s+|\s+by\s+", name):
        part = part.strip()
        words = normalize(part).split()
        if not words:
            continue
        if len(words) == 1 and (words[0] in _GENERIC or len(words[0]) < 4):
            continue
        if all(w in _GENERIC for w in words):
            continue
        terms.add(part)
    for extra in re.split(r"[,\n]", project.match_terms or ""):
        if extra.strip():
            terms.add(extra.strip())
    cleaned = {normalize(t).strip() for t in terms}
    return sorted((t for t in cleaned if len(t) >= 3), key=len, reverse=True)


def _display(project: Candidate, term: str) -> str:
    """The term as the person wrote it (name or match terms), for the reason text."""
    for source in [project.name, *re.split(r"[,\n]", project.match_terms or "")]:
        m = re.search(r"\b" + r"\W+".join(map(re.escape, term.split())) + r"\b", source, re.I)
        if m:
            return m.group(0)
    return term


def match_project(subject: str, text: str, links: list[str], projects: list[Candidate]) -> Match | None:
    # 1. Links
    email_slugs: set[str] = set()
    for link in links:
        email_slugs |= url_slugs(link)
    by_link = [
        p for p in projects if (url_slugs(p.campaign_url) | url_slugs(p.pledge_manager_url)) & email_slugs
    ]
    if len(by_link) == 1:
        return Match(by_link[0].id, "campaign link")

    # 2. Names. Tier 3 = subject, 2 = top of the body, 1 = anywhere.
    subj = normalize(subject)
    head = normalize(text[:800])
    body = normalize(text)
    pool = by_link or projects
    scored: list[tuple[int, int, Candidate, str]] = []
    for p in pool:
        best: tuple[int, int, str] | None = None
        for term in name_terms(p):
            needle = f" {term} "
            tier = 3 if needle in subj else 2 if needle in head else 1 if needle in body else 0
            if tier and (best is None or (tier, len(term)) > best[:2]):
                best = (tier, len(term), term)
        if best:
            scored.append((best[0], best[1], p, best[2]))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    top = scored[0]
    if len(scored) > 1 and scored[1][:2] == top[:2]:
        return None  # two pledges equally likely: let the person decide
    if top[0] == 1 and len(scored) > 1:
        return None  # only buried mentions, and more than one pledge mentioned
    where = {3: "subject", 2: "body", 1: "body"}[top[0]]
    return Match(top[2].id, f'"{_display(top[2], top[3].strip())}" in {where}')
