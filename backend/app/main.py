from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .routes import router
from .seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if db.SessionLocal is None:
        db.init_db()
    seed_file = os.environ.get("CROWDTRACKER_SEED_FILE")
    if seed_file:
        assert db.SessionLocal is not None
        with db.SessionLocal() as session:
            seed_if_empty(session, Path(seed_file))
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="crowdtracker", version=__version__, lifespan=lifespan)
    app.include_router(router)

    static_dir = Path(os.environ.get("CROWDTRACKER_STATIC", Path(__file__).resolve().parent.parent / "static"))
    if static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (static_dir / path).resolve()
            # Serve real files (favicon etc.) but never anything outside static_dir.
            if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
