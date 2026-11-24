import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "./api";
import { Icon } from "./Icon";
import { ProjectForm, periodError } from "./ProjectForm";
import { Rewards } from "./Rewards";
import { PlatformChip } from "./ProjectList";
import { describeSchedule } from "./SlipTrack";
import type { EventKind, ProjectDetail, ProjectInput, Stage } from "./types";
import { KIND_LABEL, MANUAL_KINDS, PLATFORM_LABEL, STAGES, STAGE_LABEL, formatDay, money, months } from "./vocab";

function toInput(p: ProjectDetail): ProjectInput {
  return {
    name: p.name,
    category: p.category,
    creator: p.creator,
    funded_on: p.funded_on,
    pledge_manager: p.pledge_manager,
    campaign_url: p.campaign_url,
    pledge_manager_url: p.pledge_manager_url,
    tier: p.tier,
    pledge_amount: p.pledge_amount,
    currency: p.currency,
    campaign_ended: p.campaign_ended,
    original_est: p.original_est,
    current_est: p.current_est,
    stage: p.stage,
    received_on: p.received_on,
    notes: p.notes,
  };
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function ProjectPanel({
  projectId,
  onClose,
  onChanged,
  onDeleted,
}: {
  projectId: number;
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [estimate, setEstimate] = useState("");
  const [entryTitle, setEntryTitle] = useState("");
  const [entryKind, setEntryKind] = useState<EventKind>("update");
  const [entryDate, setEntryDate] = useState(todayIso());
  const [entryUrl, setEntryUrl] = useState("");

  async function load() {
    setLoadError(null);
    try {
      const p = await api.getProject(projectId);
      setProject(p);
      setEstimate(p.current_est ?? "");
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Couldn't load this pledge.");
    }
  }

  useEffect(() => {
    setProject(null);
    setEditing(false);
    setConfirmDelete(false);
    setActionError(null);
    setEntryTitle("");
    setEntryUrl("");
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const patch = (changes: Partial<ProjectInput>) =>
    run(async () => {
      const updated = await api.updateProject(projectId, changes);
      setProject(updated);
      setEstimate(updated.current_est ?? "");
      onChanged();
    });

  const estimateError = periodError(estimate);
  const estimateDirty = project !== null && estimate.trim().toUpperCase() !== (project.current_est ?? "");

  function saveEstimate(e: FormEvent) {
    e.preventDefault();
    if (estimateError || !estimateDirty) return;
    void patch({ current_est: estimate.trim() || null });
  }

  function addEntry(e: FormEvent) {
    e.preventDefault();
    if (!entryTitle.trim()) return;
    void run(async () => {
      await api.addEvent(projectId, {
        title: entryTitle.trim(),
        kind: entryKind,
        occurred_on: entryDate || null,
        body: null,
        url: entryUrl.trim() || null,
      });
      setEntryTitle("");
      setEntryUrl("");
      await load();
      onChanged();
    });
  }

  if (loadError) {
    return (
      <div className="panel-body">
        <PanelBar title="Pledge" onClose={onClose} />
        <p className="banner banner-error" role="alert">
          <Icon name="alert" /> {loadError}
        </p>
        <button type="button" className="btn" onClick={() => void load()}>
          Try again
        </button>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="panel-body" aria-busy="true">
        <PanelBar title="Loading…" onClose={onClose} />
        <div className="skeleton">
          <span className="skeleton-bar" style={{ width: "60%" }} />
          <span className="skeleton-bar" style={{ width: "40%" }} />
          <span className="skeleton-bar" style={{ width: "75%" }} />
        </div>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="panel-body">
        <PanelBar title={`Edit ${project.name}`} onClose={() => setEditing(false)} closeLabel="Stop editing" />
        <ProjectForm
          key={project.id}
          initial={toInput(project)}
          submitLabel="Save changes"
          onCancel={() => setEditing(false)}
          onSubmit={async (input) => {
            const updated = await api.updateProject(project.id, input);
            setProject(updated);
            setEstimate(updated.current_est ?? "");
            setEditing(false);
            onChanged();
          }}
        />
      </div>
    );
  }

  const schedule = describeSchedule(project);

  return (
    <div className="panel-body">
      <PanelBar title={project.name} onClose={onClose} />

      <div className="panel-meta">
        <PlatformChip platform={project.funded_on} />
        <span className={`schedule schedule-${schedule.tone}`}>{schedule.text}</span>
        {[project.category, project.creator].filter(Boolean).map((t) => (
          <span key={t} className="sub">
            {t}
          </span>
        ))}
      </div>

      {actionError && (
        <p className="banner banner-error" role="alert">
          <Icon name="alert" /> {actionError}
        </p>
      )}

      <section className="panel-section" aria-labelledby="status-heading">
        <h3 id="status-heading">Status</h3>
        {project.stage === "delivered" ? (
          <div className="received">
            <p>
              <strong>Received{project.received_on ? ` ${formatDay(project.received_on)}` : ""}</strong>
              {project.received_on && (
                <span className="hint"> {describeSchedule(project).text.replace(/^Received ?/, "") || ""}</span>
              )}
            </p>
            <label className="field">
              <span className="field-label">Received on</span>
              <input
                type="date"
                value={project.received_on ?? ""}
                disabled={busy}
                onChange={(e) => e.target.value && void patch({ received_on: e.target.value })}
              />
            </label>
          </div>
        ) : (
          project.stage !== "cancelled" && (
            <button
              type="button"
              className="btn btn-primary btn-received"
              disabled={busy}
              onClick={() => void patch({ stage: "delivered" })}
            >
              <Icon name="check" /> {project.rewards.length > 0 ? "Mark everything received" : "Mark as received"}
            </button>
          )
        )}
        <label className="field">
          <span className="field-label">Stage</span>
          <select
            value={project.stage}
            disabled={busy}
            onChange={(e) => void patch({ stage: e.target.value as Stage })}
          >
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        {project.stage !== "delivered" && (
        <form className="field" onSubmit={saveEstimate}>
          <label className="field-label" htmlFor="quick-estimate">
            Now expected
          </label>
          <div className="input-with-button">
            <input
              id="quick-estimate"
              value={estimate}
              onChange={(e) => setEstimate(e.target.value)}
              placeholder={project.original_est ?? "2027-Q2"}
              aria-invalid={!!estimateError}
              aria-describedby="quick-estimate-hint"
              autoComplete="off"
            />
            <button type="submit" className="btn" disabled={busy || !estimateDirty || !!estimateError}>
              Update
            </button>
          </div>
          <span id="quick-estimate-hint" className={estimateError ? "hint hint-error" : "hint"}>
            {estimateError ??
              (project.original_est_label
                ? `Promised ${project.original_est_label}. Each change is logged below.`
                : "Each change is logged below.")}
          </span>
        </form>
        )}
      </section>

      <Rewards
        project={project}
        busy={busy}
        run={run}
        onUpdated={(updated) => {
          setProject(updated);
          onChanged();
        }}
      />

      <section className="panel-section" aria-labelledby="pledge-heading">
        <h3 id="pledge-heading">Pledge</h3>
        <dl className="facts">
          <dt>Pledged on</dt>
          <dd>{PLATFORM_LABEL[project.funded_on]}</dd>
          <dt>Campaign ended</dt>
          <dd className="num">
            {project.campaign_ended ? (
              <>
                {formatDay(project.campaign_ended)}
                {project.months_since_campaign !== null && project.months_since_campaign > 0 && (
                  <span className="facts-aside"> · {months(project.months_since_campaign)} ago</span>
                )}
              </>
            ) : (
              <button type="button" className="link-button" onClick={() => setEditing(true)}>
                Add date
              </button>
            )}
          </dd>
          <dt>Survey on</dt>
          <dd>{project.pledge_manager ? PLATFORM_LABEL[project.pledge_manager] : "Not announced"}</dd>
          {project.tier && (
            <>
              <dt>Tier</dt>
              <dd>{project.tier}</dd>
            </>
          )}
          {project.pledge_amount !== null && (
            <>
              <dt>Amount</dt>
              <dd className="num">{money(project.pledge_amount, project.currency)}</dd>
            </>
          )}
        </dl>
        {(project.campaign_url || project.pledge_manager_url) && (
          <p className="links">
            {project.campaign_url && (
              <a href={project.campaign_url} target="_blank" rel="noreferrer noopener">
                Campaign page <Icon name="external" size={14} />
              </a>
            )}
            {project.pledge_manager_url && (
              <a href={project.pledge_manager_url} target="_blank" rel="noreferrer noopener">
                Pledge manager <Icon name="external" size={14} />
              </a>
            )}
          </p>
        )}
        {project.notes && <p className="notes">{project.notes}</p>}
      </section>

      <section className="panel-section" aria-labelledby="timeline-heading">
        <h3 id="timeline-heading">Timeline</h3>
        <form className="entry-form" onSubmit={addEntry}>
          <label className="field">
            <span className="field-label">Log an entry</span>
            <input
              value={entryTitle}
              onChange={(e) => setEntryTitle(e.target.value)}
              placeholder="Update 14: files sent to the printer"
              maxLength={300}
              autoComplete="off"
            />
          </label>
          <div className="field-row">
            <label className="field">
              <span className="field-label">Type</span>
              <select value={entryKind} onChange={(e) => setEntryKind(e.target.value as EventKind)}>
                {MANUAL_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Date</span>
              <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
            </label>
          </div>
          <label className="field">
            <span className="field-label">Link (optional)</span>
            <input type="url" value={entryUrl} onChange={(e) => setEntryUrl(e.target.value)} placeholder="https://" />
          </label>
          <button type="submit" className="btn" disabled={busy || !entryTitle.trim()}>
            Add to timeline
          </button>
        </form>

        {project.events.length === 0 ? (
          <p className="empty-inline">
            Nothing logged yet. Add creator updates, survey invites and charges here; date and stage changes are
            recorded for you.
          </p>
        ) : (
          <ol className="timeline">
            {project.events.map((ev) => (
              <li key={ev.id} className={`timeline-item kind-${ev.kind}`}>
                <div className="timeline-head">
                  <span className="timeline-kind">{KIND_LABEL[ev.kind]}</span>
                  <time dateTime={ev.occurred_on} className="num">
                    {formatDay(ev.occurred_on)}
                  </time>
                </div>
                <p className="timeline-title">
                  {ev.url ? (
                    <a href={ev.url} target="_blank" rel="noreferrer noopener">
                      {ev.title}
                    </a>
                  ) : (
                    ev.title
                  )}
                </p>
                {ev.source === "manual" && (
                  <button
                    type="button"
                    className="icon-button timeline-remove"
                    aria-label={`Remove entry: ${ev.title}`}
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await api.deleteEvent(ev.id);
                        await load();
                        onChanged();
                      })
                    }
                  >
                    <Icon name="close" size={14} />
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="panel-footer">
        <button type="button" className="btn" onClick={() => setEditing(true)}>
          <Icon name="edit" /> Edit details
        </button>
        {confirmDelete ? (
          <span className="confirm">
            <span>Delete this pledge and its timeline?</span>
            <button
              type="button"
              className="btn btn-danger"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await api.deleteProject(project.id);
                  onDeleted();
                })
              }
            >
              Delete
            </button>
            <button type="button" className="btn" onClick={() => setConfirmDelete(false)}>
              Keep
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn-quiet-danger" onClick={() => setConfirmDelete(true)}>
            <Icon name="trash" /> Delete
          </button>
        )}
      </div>
    </div>
  );
}

export function PanelBar({
  title,
  onClose,
  closeLabel = "Close",
}: {
  title: string;
  onClose: () => void;
  closeLabel?: string;
}) {
  return (
    <div className="panel-bar">
      <button type="button" className="icon-button panel-back" onClick={onClose} aria-label={closeLabel}>
        <Icon name="back" size={18} />
      </button>
      <h2>{title}</h2>
      <button type="button" className="icon-button panel-close" onClick={onClose} aria-label={closeLabel}>
        <Icon name="close" size={18} />
      </button>
    </div>
  );
}
