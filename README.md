<p>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" alt="crowdtracker" height="48">
  </picture>
</p>

Self-hosted tracker for crowdfunding pledges: what you backed, where the pledge
and its survey live, when it was promised, when it is expected now, and how far
it has slipped.

FastAPI + SQLite backend, React front end, one container.

## What v1 does

- Tracks each pledge's funding platform and pledge manager separately
  (Kickstarter, BackerKit, Gamefound, PledgeManager, Indiegogo, other).
- Keeps the **promised** date and the **latest estimate** apart, so slips are
  measured instead of overwritten.
- Flags pledges that are past their latest estimate and pledges with a survey
  waiting on you.
- Keeps a timeline per pledge. Creator updates, surveys, charges and shipping
  notices are logged by hand; estimate and stage changes are logged for you.
- Works on a phone and follows the system light/dark setting.

Everything is entered by hand in v1. See [Roadmap](#roadmap) for email ingestion.

## Estimates

Delivery estimates are rarely a day, so they are stored as a period:

| You type     | Means          | Overdue after |
| ------------ | -------------- | ------------- |
| `2027`       | sometime 2027  | Dec 31, 2027  |
| `2027-Q2`    | Q2 2027        | Jun 30, 2027  |
| `2027-08`    | August 2027    | Aug 31, 2027  |
| `2027-08-15` | that day       | Aug 15, 2027  |

## Run it locally

```sh
# API on :8000
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
CROWDTRACKER_SEED_FILE=seed/projects.example.json uvicorn app.main:app --reload

# UI on :5173, proxying /api to :8000
cd frontend
npm install
npm run dev
```

Tests: `cd backend && pytest`.

## Deploy

Images are published to GitHub Container Registry for `linux/amd64` and
`linux/arm64`:

```sh
podman pull ghcr.io/hunter-read/crowdtracker:latest
podman compose up -d
```

| Tag           | Built from                         |
| ------------- | ---------------------------------- |
| `latest`      | the newest commit on `main`        |
| `sha-<short>` | every commit on `main`             |
| `1.2.3`, `1.2`| a `v1.2.3` git tag                 |

`compose.yaml` assumes Traefik and uses common names for the network, entrypoint
and middleware; the lines to check are marked `ADJUST`.

**There is no login.** Put it behind your forward-auth middleware or keep it on
a private network.

The container runs as a non-root user (UID 10001) and writes only to `/data`.

| Variable                 | Default                 | Purpose                                              |
| ------------------------ | ----------------------- | ---------------------------------------------------- |
| `CROWDTRACKER_DB`        | `/data/crowdtracker.db` | SQLite file                                          |
| `CROWDTRACKER_SEED_FILE` | unset                   | JSON file to load at startup if the database is empty |
| `CROWDTRACKER_STATIC`    | `/app/static`           | Built front end to serve                             |

Back up by copying the SQLite file (`sqlite3 crowdtracker.db ".backup out.db"`
while running).

## Loading your pledges

Your pledge list is personal, so it is not part of this repo; only
[`backend/seed/projects.example.json`](backend/seed/projects.example.json) is.
Write your own file in that shape, then either:

- **Import into a running instance** (adds to whatever is there):

  ```sh
  curl -X POST --json @my-pledges.json https://crowdtracker.example.com/api/import
  ```

- **Seed an empty database at startup:** copy the file into the data volume and
  set `CROWDTRACKER_SEED_FILE=/data/seed.json`.

Any other `*.json` under `backend/seed/` is git-ignored.

## API

Interactive docs at `/docs`.

| Method | Path                         |                                                   |
| ------ | ---------------------------- | ------------------------------------------------- |
| GET    | `/api/projects?view=`        | `all`, `open`, `overdue`, `action`, `closed`      |
| POST   | `/api/projects`              |                                                   |
| GET    | `/api/projects/{id}`         | includes the timeline                             |
| PATCH  | `/api/projects/{id}`         | partial; logs estimate and stage changes          |
| DELETE | `/api/projects/{id}`         |                                                   |
| POST   | `/api/projects/{id}/events`  |                                                   |
| DELETE | `/api/events/{id}`           |                                                   |
| POST   | `/api/import`                | JSON list of projects                             |
| GET    | `/api/summary`               | counts, handy for a dashboard widget              |
| GET    | `/api/health`                |                                                   |

## Roadmap

1. **Email ingestion.** Poll an IMAP folder, match platform emails (updates,
   survey invites, charges, shipping notices) to a pledge, and append them to
   its timeline with `source: "email"`. Unmatched mail goes to a review queue.
2. **Platform enrichment.** Gamefound's public API for campaign metadata;
   public campaign pages for update counts. None of the platforms offers a
   backer-facing API for your own pledges.
3. Kickstarter data-export import (the CSV bundle from a privacy request).

## Design

See [DESIGN.md](DESIGN.md). Platform colours are in `frontend/src/styles.css`.
The logo files are in `assets/`; `assets/build_logo.py` regenerates them.
