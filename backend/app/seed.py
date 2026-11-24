"""Load starter data into an empty database.

    python -m app.seed path/to/projects.json

The file is a JSON list of projects in the same shape the API accepts; see
seed/projects.example.json. Does nothing if the projects table already has rows.

Setting CROWDTRACKER_SEED_FILE does the same thing at startup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import db
from .models import Project
from .schemas import ProjectCreate

EXAMPLE_SEED = Path(__file__).resolve().parent.parent / "seed" / "projects.example.json"


def seed_if_empty(session: Session, path: Path) -> int:
    if session.scalar(select(func.count()).select_from(Project)):
        return 0
    if not path.is_file():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        session.add(Project(**ProjectCreate(**row).model_dump()))
    session.commit()
    return len(rows)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.seed path/to/projects.json")
    db.init_db()
    assert db.SessionLocal is not None
    with db.SessionLocal() as session:
        count = seed_if_empty(session, Path(sys.argv[1]))
    print(f"Seeded {count} projects" if count else "Nothing to seed (database not empty or file missing)")


if __name__ == "__main__":
    main()
