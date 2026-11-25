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
  (Kickstarter, BackerKit, Gamefound, PledgeManager, PledgeBox, Indiegogo, other).
- Keeps the **promised** date and the **latest estimate** apart, so slips are
  measured instead of overwritten.
- Records when the campaign ended, so each pledge's timeline starts there.
- Flags pledges that are past their latest estimate and pledges with a survey
  waiting on you.
- Tracks reward items (digital or physical) that arrive separately or in
  stages. Receiving some moves a pledge to **Partly received**; receiving all
  of them moves it to **Received** and records how late it was.
- Keeps a timeline per pledge. Estimate and stage changes are logged for you.
- Reads platform email from an IMAP folder (a Gmail label works): creator
  updates, survey invites, charges, address locks and shipping notices land on
  the right pledge's timeline and move its stage forward. See [Email](#email).
- Works on a phone and follows the system light/dark setting.

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
| `CROWDTRACKER_TZ`        | `TZ`, else UTC          | IANA time zone for "today" (e.g. `America/Los_Angeles`) |

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

Upgrading keeps your data: new columns and tables are added to an existing
database at startup.

## Email

crowdtracker can read the mail the platforms already send you. It never signs
in to Kickstarter, BackerKit or Gamefound; it only reads one mail folder.

**What happens to each email**

- Mail that isn't from Kickstarter, BackerKit, Gamefound, PledgeManager,
  PledgeBox or Indiegogo is ignored and never stored. Only an excerpt of
  platform mail is kept.
- It's matched to a pledge by a campaign or pledge-manager link in the email,
  otherwise by the pledge's name (whole words, so "Crows" won't match
  "Crowsworn") or the extra names in **Also known as in emails** on the pledge.
- A match becomes a timeline entry marked *Email*. Personal notices also move
  the stage forward: a survey invite to *Survey open*, "we received your order"
  to *Survey done*, a successful charge to *Charged*, a locked address to
  *Address locked*, a shipping notice to *Shipping*. Creator updates never
  move the stage, even when they talk about shipping, and nothing moves a
  pledge backwards or past *Partly received*.
- If no pledge matches, or two match equally well, the email waits under
  **Email → To sort**, where you add it to a pledge, start a new pledge from
  it, or ignore it.
- The folder is opened read-only: nothing is marked read, moved or deleted.

**Gmail setup**

1. Create a label, e.g. `crowdfunding`, and a filter that applies it:
   `from:(kickstarter.com OR backerkit.com OR gamefound.com OR pledgemanager.com OR pledgebox.com OR indiegogo.com)`.
   Tick "Also apply filter to matching conversations" to label old mail too.
2. Create an app password at <https://myaccount.google.com/apppasswords>
   (needs 2-Step Verification). It keeps working until you revoke it.
3. Set the variables below, e.g. in `compose.yaml`, and restart.

Any IMAP server works the same way; for a separate mailbox, point
`CROWDTRACKER_IMAP_FOLDER` at its inbox.

| Variable                           | Default | Purpose                                                       |
| ---------------------------------- | ------- | ------------------------------------------------------------- |
| `CROWDTRACKER_IMAP_HOST`           | unset   | e.g. `imap.gmail.com`. Email checking is off until it's set   |
| `CROWDTRACKER_IMAP_USER`           | unset   | full address                                                  |
| `CROWDTRACKER_IMAP_PASSWORD`       | unset   | app password, or use `_PASSWORD_FILE`                         |
| `CROWDTRACKER_IMAP_PASSWORD_FILE`  | unset   | file holding the password (e.g. a Podman/Docker secret)       |
| `CROWDTRACKER_IMAP_FOLDER`         | `INBOX` | folder or Gmail label, e.g. `crowdfunding`                    |
| `CROWDTRACKER_IMAP_INTERVAL`       | `15`    | minutes between checks; `0` checks only when you press Check now |
| `CROWDTRACKER_IMAP_SINCE_DAYS`     | `365`   | how far back the first check reads                            |
| `CROWDTRACKER_IMAP_PORT`           | `993`   |                                                               |
| `CROWDTRACKER_IMAP_SECURITY`       | `ssl`   | `ssl`, `starttls` or `none`                                   |
| `CROWDTRACKER_IMAP_ALL_SENDERS`    | `false` | read every message in the folder, not just platform senders   |

Emails you forwarded by hand are understood too (the original sender is read
from the forwarded header), but the IMAP search only asks for platform senders
unless `CROWDTRACKER_IMAP_ALL_SENDERS=true`. You can also drop saved `.eml`
files on **Email → Add .eml files**, or:

```sh
curl --data-binary @update.eml -H 'Content-Type: message/rfc822' https://crowdtracker.example.com/api/inbox/upload
```

## API

Interactive docs at `/docs`.

| Method | Path                         |                                                   |
| ------ | ---------------------------- | ------------------------------------------------- |
| GET    | `/api/projects?view=`        | `all`, `open`, `overdue`, `action`, `partial`, `received`, `cancelled` |
| POST   | `/api/projects`              |                                                   |
| GET    | `/api/projects/{id}`         | includes the timeline                             |
| PATCH  | `/api/projects/{id}`         | partial; logs estimate and stage changes          |
| DELETE | `/api/projects/{id}`         |                                                   |
| POST   | `/api/projects/{id}/events`  |                                                   |
| DELETE | `/api/events/{id}`           |                                                   |
| POST   | `/api/import`                | JSON list of projects (may include `rewards`)     |
| POST   | `/api/projects/{id}/rewards` | add a reward item                                 |
| PATCH  | `/api/rewards/{id}`          | e.g. `{"received_on": "2026-11-24"}`              |
| DELETE | `/api/rewards/{id}`          |                                                   |
| GET    | `/api/summary`               | counts, handy for a dashboard widget              |
| GET    | `/api/inbox?status=`         | `unsorted` (default), `matched`, `ignored`, `all` |
| GET    | `/api/inbox/status`          | email settings, last check, errors                |
| POST   | `/api/inbox/sync`            | check the mail folder now                         |
| POST   | `/api/inbox/upload`          | raw `.eml` as the body                            |
| POST   | `/api/inbox/{id}/assign`     | `{"project_id": 3}`                               |
| POST   | `/api/inbox/{id}/ignore`     |                                                   |
| POST   | `/api/inbox/{id}/unsort`     | back to the tray; removes its timeline entry      |
| GET    | `/api/health`                |                                                   |

## Roadmap

1. **Browser button.** A Firefox/Chrome extension that sends the pledge page
   you're looking at (tier, items, order status) to crowdtracker using your
   browser's own sign-in.
2. **Platform enrichment.** Gamefound's public API for campaign metadata;
   public campaign pages for update counts. None of the platforms offers a
   backer-facing API for your own pledges.
3. Kickstarter data-export import (the CSV bundle from a privacy request).

## Design

See [DESIGN.md](DESIGN.md). Platform colours are in `frontend/src/styles.css`.
The logo files are in `assets/`; `assets/build_logo.py` regenerates them.
