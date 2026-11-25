import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { Icon } from "./Icon";
import { PanelBar } from "./ProjectPanel";
import { PlatformChip } from "./ProjectList";
import type { InboxMessage, InboxStatus, MailStatus, Project, SyncResult } from "./types";
import { CLOSED, KIND_LABEL, STAGE_LABEL, formatDay } from "./vocab";

const TABS: { id: InboxStatus; label: string }[] = [
  { id: "unsorted", label: "To sort" },
  { id: "matched", label: "Added" },
  { id: "ignored", label: "Ignored" },
];

const EMPTY_TAB: Record<InboxStatus, string> = {
  unsorted: "Nothing to sort. Emails crowdtracker can match to a pledge go straight onto its timeline.",
  matched: "No emails added to pledges yet.",
  ignored: "Nothing ignored.",
};

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  return formatDay(iso.slice(0, 10));
}

function localDay(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function describeSync(r: SyncResult): string {
  if (!r.ok) return r.error ?? "The check failed.";
  const fresh = r.matched + r.unsorted;
  if (fresh === 0) return r.fetched ? "No new platform emails." : "No new emails.";
  const parts = [];
  if (r.matched) parts.push(`${r.matched} added to pledges`);
  if (r.unsorted) parts.push(`${r.unsorted} to sort`);
  return `Found ${fresh} new ${fresh === 1 ? "email" : "emails"}: ${parts.join(", ")}.`;
}

export function InboxPanel({
  projects,
  onClose,
  onChanged,
  onOpenProject,
  onNewPledge,
}: {
  projects: Project[];
  onClose: () => void;
  onChanged: () => void;
  onOpenProject: (id: number) => void;
  onNewPledge: (message: InboxMessage) => void;
}) {
  const [tab, setTab] = useState<InboxStatus>("unsorted");
  const [messages, setMessages] = useState<InboxMessage[] | null>(null);
  const [status, setStatus] = useState<MailStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [list, st] = await Promise.all([api.listInbox(tab), api.mailStatus()]);
      setMessages(list);
      setStatus(st);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your email.");
    }
  }, [tab]);

  useEffect(() => {
    setMessages(null);
    void load();
  }, [load]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const checkNow = () =>
    run(async () => {
      setNotice(null);
      const result = await api.syncMail();
      if (result.ok) setNotice(describeSync(result));
      else setError(describeSync(result));
    });

  const uploadFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    void run(async () => {
      setNotice(null);
      const outcomes: string[] = [];
      for (const file of Array.from(files)) {
        try {
          const r = await api.uploadEmail(file);
          outcomes.push(r.outcome);
        } catch (err) {
          outcomes.push(err instanceof ApiError && err.status === 422 ? "skipped" : "failed");
        }
      }
      const count = (o: string) => outcomes.filter((x) => x === o).length;
      const parts = [
        count("matched") && `${count("matched")} added to pledges`,
        count("unsorted") && `${count("unsorted")} to sort`,
        count("duplicate") && `${count("duplicate")} already here`,
        count("skipped") && `${count("skipped")} not from a crowdfunding platform`,
        count("failed") && `${count("failed")} failed`,
      ].filter(Boolean);
      setNotice(`${parts.join(", ")}.`.replace(/^./, (c) => c.toUpperCase()));
      if (fileInput.current) fileInput.current.value = "";
    });
  };

  // Open pledges first, then the rest, each alphabetical.
  const choices = useMemo(
    () =>
      [...projects].sort(
        (a, b) =>
          Number(CLOSED.includes(a.stage)) - Number(CLOSED.includes(b.stage)) || a.name.localeCompare(b.name),
      ),
    [projects],
  );

  return (
    <div className="panel-body">
      <PanelBar title="Email" onClose={onClose} />

      <section className="mail-status" aria-label="Email checking">
        {status === null ? (
          <p className="hint">Checking…</p>
        ) : status.configured ? (
          <>
            <p>
              Reading <strong>{status.folder}</strong> on {status.host}
              {status.interval_minutes ? ` every ${status.interval_minutes} min` : " when you ask"}.{" "}
              <span className="hint">
                {status.last_sync_at ? `Last checked ${ago(status.last_sync_at)}.` : "Not checked yet."}
              </span>
            </p>
            {status.last_error && (
              <p className="banner banner-error" role="alert">
                <Icon name="alert" /> <span>{status.last_error}</span>
              </p>
            )}
          </>
        ) : (
          <p>
            Email checking is off. Point crowdtracker at a mail folder with the <code>CROWDTRACKER_IMAP_*</code>{" "}
            settings (see the README), or add saved emails by hand below.
          </p>
        )}
        <div className="mail-actions">
          {status?.configured && (
            <button type="button" className="btn" disabled={busy} onClick={() => void checkNow()}>
              <Icon name="refresh" /> {busy ? "Checking…" : "Check now"}
            </button>
          )}
          <label className={busy ? "btn btn-file btn-disabled" : "btn btn-file"}>
            <Icon name="upload" /> Add .eml files
            <input
              ref={fileInput}
              type="file"
              accept=".eml,message/rfc822"
              multiple
              disabled={busy}
              onChange={(e) => uploadFiles(e.target.files)}
            />
          </label>
        </div>
        {notice && (
          <p className="mail-notice" role="status">
            {notice}
          </p>
        )}
      </section>

      <nav className="views views-small" aria-label="Email">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={["view", tab === t.id ? "view-on" : "", t.id === "unsorted" && (status?.unsorted ?? 0) > 0 ? "view-action" : ""].join(" ")}
            aria-pressed={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === "unsorted" && <span className="view-count num">{status?.unsorted ?? "–"}</span>}
          </button>
        ))}
      </nav>

      {error && (
        <p className="banner banner-error" role="alert">
          <Icon name="alert" /> <span>{error}</span>
        </p>
      )}

      {messages === null && !error && (
        <div className="skeleton" aria-busy="true">
          <span className="skeleton-bar" style={{ width: "70%" }} />
          <span className="skeleton-bar" style={{ width: "50%" }} />
        </div>
      )}

      {messages !== null && messages.length === 0 && <p className="empty-inline">{EMPTY_TAB[tab]}</p>}

      {messages !== null && messages.length > 0 && (
        <ol className="mail-list">
          {messages.map((m) => (
            <MessageItem
              key={m.id}
              message={m}
              projects={choices}
              busy={busy}
              onAssign={(projectId) => void run(async () => void (await api.assignMessage(m.id, projectId)))}
              onIgnore={() => void run(async () => void (await api.ignoreMessage(m.id)))}
              onUnsort={() => void run(async () => void (await api.unsortMessage(m.id)))}
              onNewPledge={() => onNewPledge(m)}
              onOpenProject={onOpenProject}
            />
          ))}
        </ol>
      )}
    </div>
  );
}

function MessageItem({
  message: m,
  projects,
  busy,
  onAssign,
  onIgnore,
  onUnsort,
  onNewPledge,
  onOpenProject,
}: {
  message: InboxMessage;
  projects: Project[];
  busy: boolean;
  onAssign: (projectId: number) => void;
  onIgnore: () => void;
  onUnsort: () => void;
  onNewPledge: () => void;
  onOpenProject: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<string>("");
  // Links are offered as buttons below, so bare URLs only add noise here.
  const excerpt = (m.excerpt ?? "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const long = excerpt.length > 260;
  const selectId = `assign-${m.id}`;

  return (
    <li className="mail-item">
      <div className="mail-head">
        <PlatformChip platform={m.platform} />
        <span className="timeline-kind">{KIND_LABEL[m.kind]}</span>
        {m.stage_hint && <span className="sub-inline">→ {STAGE_LABEL[m.stage_hint]}</span>}
        <time dateTime={m.received_at} className="num mail-date">
          {formatDay(localDay(m.received_at))}
        </time>
      </div>
      <p className="mail-subject">{m.subject}</p>
      <p className="sub">{m.sender}</p>

      {excerpt && (
        <div className="mail-excerpt">
          <p className={open ? "" : "mail-clamp"}>{open || !long ? excerpt : `${excerpt.slice(0, 260)}…`}</p>
          {long && (
            <button type="button" className="link-button" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}

      {(m.url || m.tracking_url) && (
        <p className="links">
          {m.url && (
            <a href={m.url} target="_blank" rel="noreferrer noopener">
              Open on site <Icon name="external" size={14} />
            </a>
          )}
          {m.tracking_url && (
            <a href={m.tracking_url} target="_blank" rel="noreferrer noopener">
              Tracking <Icon name="external" size={14} />
            </a>
          )}
        </p>
      )}

      {m.status === "unsorted" && (
        <div className="mail-actions">
          <label className="visually-hidden" htmlFor={selectId}>
            Pledge for this email
          </label>
          <select id={selectId} value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
            <option value="">Choose a pledge…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !choice}
            onClick={() => onAssign(Number(choice))}
          >
            Add to pledge
          </button>
          <button type="button" className="btn" disabled={busy} onClick={onNewPledge}>
            <Icon name="plus" /> New pledge
          </button>
          <button type="button" className="btn btn-quiet" disabled={busy} onClick={onIgnore}>
            Ignore
          </button>
        </div>
      )}

      {m.status === "matched" && (
        <div className="mail-actions">
          <span className="mail-matched">
            <Icon name="check" size={14} /> Added to{" "}
            {m.project_id ? (
              <button type="button" className="link-button" onClick={() => onOpenProject(m.project_id!)}>
                {m.project_name}
              </button>
            ) : (
              "a deleted pledge"
            )}
            {m.match_reason && <span className="hint"> ({m.match_reason})</span>}
          </span>
          <button type="button" className="btn btn-quiet" disabled={busy} onClick={onUnsort}>
            Wrong pledge
          </button>
        </div>
      )}

      {m.status === "ignored" && (
        <div className="mail-actions">
          <button type="button" className="btn btn-quiet" disabled={busy} onClick={onUnsort}>
            Put back
          </button>
        </div>
      )}
    </li>
  );
}
