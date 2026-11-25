import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import { Icon } from "./Icon";
import { InboxPanel } from "./InboxPanel";
import { EMPTY_PROJECT, ProjectForm } from "./ProjectForm";
import { ListSkeleton, ProjectList, type Sort, type SortKey } from "./ProjectList";
import { PanelBar, ProjectPanel } from "./ProjectPanel";
import { buildAxis } from "./SlipTrack";
import type { InboxMessage, Platform, Project, ProjectInput } from "./types";
import { CLOSED, PLATFORMS, PLATFORM_LABEL, STAGES } from "./vocab";


type View = "open" | "overdue" | "action" | "partial" | "received" | "cancelled" | "all";

const VIEWS: { id: View; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "overdue", label: "Overdue" },
  { id: "action", label: "Needs you" },
  { id: "partial", label: "Partly received" },
  { id: "received", label: "Received" },
  { id: "cancelled", label: "Cancelled" },
  { id: "all", label: "All" },
];

const inView = (p: Project, view: View): boolean => {
  switch (view) {
    case "open":
      return !CLOSED.includes(p.stage);
    case "overdue":
      return p.overdue;
    case "action":
      return p.needs_action;
    case "partial":
      return p.stage === "partial";
    case "received":
      return p.stage === "delivered";
    case "cancelled":
      return p.stage === "cancelled";
    default:
      return true;
  }
};

const EMPTY_VIEW: Record<View, string> = {
  open: "No open pledges. Everything you've backed has been delivered or cancelled.",
  overdue: "Nothing is overdue. Every open pledge is still inside its latest estimate.",
  action: "Nothing is waiting on you. Pledges show up here while a survey is open.",
  received: "Nothing received yet. Open a pledge and choose Mark as received when it arrives.",
  cancelled: "No cancelled pledges.",
  partial: "Nothing is partly received.",
  all: "",
};

type PanelState =
  | { mode: "none" }
  | { mode: "new"; from?: InboxMessage }
  | { mode: "detail"; id: number }
  | { mode: "inbox" };

/** A starting point for a pledge made from an email in the tray. */
function draftFrom(message: InboxMessage): ProjectInput {
  // The campaign link's slug is usually the project's name; the subject is the fallback.
  const slug = message.campaign_url?.replace(/[?#].*$/, "").split("/").filter(Boolean).pop();
  const fromSlug = slug
    ? slug
        .split("-")
        .slice(0, 8)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ")
    : null;
  const name = fromSlug ?? message.subject
    .replace(/^\s*(project )?update\s*#\s*\d+\s*[:\-–]\s*/i, "")
    .replace(/\s*[-–|]\s*(kickstarter|backerkit|gamefound)\s*$/i, "")
    .trim();
  return {
    ...EMPTY_PROJECT,
    name,
    funded_on: message.platform,
    campaign_url: message.campaign_url,
  };
}

export default function App() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("open");
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [sort, setSort] = useState<Sort>({ key: "estimate", dir: 1 });
  const [panel, setPanel] = useState<PanelState>({ mode: "none" });
  const [unsorted, setUnsorted] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [list, mail] = await Promise.all([api.listProjects(), api.mailStatus().catch(() => null)]);
      setProjects(list);
      if (mail) setUnsorted(mail.unsorted);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your pledges.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && panel.mode !== "none") setPanel({ mode: "none" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel.mode]);

  const today = useMemo(() => {
    const d = new Date();
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  }, []);

  const all = projects ?? [];
  const axis = useMemo(() => buildAxis(all, today), [all, today]);

  const counts = useMemo(() => {
    const out = {} as Record<View, number>;
    for (const v of VIEWS) out[v.id] = all.filter((p) => inView(p, v.id)).length;
    return out;
  }, [all]);

  const viewed = useMemo(() => all.filter((p) => inView(p, view)), [all, view]);

  // The colour bar: one segment per platform, sized by how many pledges in
  // the current view were made there. Doubles as the platform filter.
  const spectrum = useMemo(
    () =>
      PLATFORMS.map((id) => ({ id, count: viewed.filter((p) => p.funded_on === id).length })).filter(
        (s) => s.count > 0,
      ),
    [viewed],
  );

  const visible = useMemo(() => {
    const rows = viewed.filter((p) => !platform || p.funded_on === platform);
    const cmp: Record<SortKey, (a: Project, b: Project) => number> = {
      name: (a, b) => a.name.localeCompare(b.name),
      stage: (a, b) => STAGES.indexOf(a.stage) - STAGES.indexOf(b.stage) || a.name.localeCompare(b.name),
      estimate: (a, b) => {
        // Undated pledges stay at the bottom in both directions.
        if (!a.effective_est_end || !b.effective_est_end) {
          if (a.effective_est_end) return -1 * sort.dir;
          if (b.effective_est_end) return 1 * sort.dir;
          return a.name.localeCompare(b.name) * sort.dir;
        }
        return a.effective_est_end.localeCompare(b.effective_est_end) || a.name.localeCompare(b.name);
      },
    };
    if (view === "received" && sort.key === "estimate") {
      // Newest arrivals first.
      return [...rows].sort(
        (a, b) => (b.received_on ?? "").localeCompare(a.received_on ?? "") || a.name.localeCompare(b.name),
      );
    }
    return [...rows].sort((a, b) => cmp[sort.key](a, b) * sort.dir);
  }, [viewed, platform, sort, view]);

  useEffect(() => {
    if (platform && !spectrum.some((s) => s.id === platform)) setPlatform(null);
  }, [platform, spectrum]);

  const onSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));

  const panelOpen = panel.mode !== "none";
  const selectedId = panel.mode === "detail" ? panel.id : null;

  return (
    <div className={panelOpen ? "app app-panel-open" : "app"}>
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="crowdtracker home">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          crowdtracker
        </a>
        <div className="topbar-actions">
          <button
            type="button"
            className={panel.mode === "inbox" ? "btn btn-ghost-ink btn-ghost-on" : "btn btn-ghost-ink"}
            onClick={() => setPanel(panel.mode === "inbox" ? { mode: "none" } : { mode: "inbox" })}
            aria-pressed={panel.mode === "inbox"}
          >
            <Icon name="inbox" /> <span className="btn-label">Email</span>
            {unsorted > 0 && (
              <span className="badge num" aria-label={`${unsorted} to sort`}>
                {unsorted}
              </span>
            )}
          </button>
          <button type="button" className="btn btn-on-ink" onClick={() => setPanel({ mode: "new" })}>
            <Icon name="plus" /> <span className="btn-label">Add pledge</span>
          </button>
        </div>
      </header>

      <div className="layout">
        <main className="main">
          <h1 className="visually-hidden">Pledges</h1>

          <nav className="views" aria-label="Views">
            {VIEWS.filter((v) => !(v.id === "cancelled" || v.id === "partial") || counts[v.id] > 0 || view === v.id).map((v) => (
              <button
                key={v.id}
                type="button"
                className={[
                  "view",
                  view === v.id ? "view-on" : "",
                  v.id === "overdue" && counts.overdue > 0 ? "view-late" : "",
                  v.id === "action" && counts.action > 0 ? "view-action" : "",
                ].join(" ")}
                aria-pressed={view === v.id}
                onClick={() => setView(v.id)}
              >
                {v.label}
                <span className="view-count num">{projects ? counts[v.id] : "–"}</span>
              </button>
            ))}
          </nav>

          {spectrum.length > 0 && (
            <div className="spectrum" role="group" aria-label="Filter by platform">
              {spectrum.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={[
                    "spectrum-seg",
                    `platform-${s.id}`,
                    platform === s.id ? "spectrum-on" : "",
                    platform && platform !== s.id ? "spectrum-dim" : "",
                  ].join(" ")}
                  style={{ flexGrow: s.count }}
                  aria-pressed={platform === s.id}
                  onClick={() => setPlatform(platform === s.id ? null : s.id)}
                >
                  <span className="spectrum-name">{PLATFORM_LABEL[s.id]}</span>
                  <span className="spectrum-count num">{s.count}</span>
                </button>
              ))}
            </div>
          )}

          {error && (
            <div className="banner banner-error" role="alert">
              <Icon name="alert" />
              <span>{error}</span>
              <button type="button" className="btn" onClick={() => void refresh()}>
                Try again
              </button>
            </div>
          )}

          {projects === null && !error && <ListSkeleton />}

          {projects !== null && all.length === 0 && (
            <div className="empty">
              <h2>Track your first pledge</h2>
              <p>
                Add each campaign you've backed with the delivery date it promised. When the creator moves the date,
                update it here and crowdtracker keeps the history, shows how far it has slipped, and flags anything
                past due.
              </p>
              <button type="button" className="btn btn-primary" onClick={() => setPanel({ mode: "new" })}>
                <Icon name="plus" /> Add pledge
              </button>
            </div>
          )}

          {projects !== null && all.length > 0 && visible.length === 0 && (
            <div className="empty">
              <p>{EMPTY_VIEW[view]}</p>
              <button type="button" className="btn" onClick={() => setView("all")}>
                Show all pledges
              </button>
            </div>
          )}

          {visible.length > 0 && (
            <>
              <ProjectList
                projects={visible}
                axis={axis}
                selectedId={selectedId}
                sort={sort}
                onSort={onSort}
                onSelect={(id) => setPanel({ mode: "detail", id })}
              />
              <p className="legend" aria-hidden="true">
                <span className="legend-item">
                  <span className="track-tick legend-tick" /> Campaign ended
                </span>
                <span className="legend-item">
                  <span className="legend-swatch track-seg-wait" /> Expected wait
                </span>
                <span className="legend-item">
                  <span className="track-dot track-dot-promised legend-dot" /> Promised
                </span>
                <span className="legend-item">
                  <span className="track-dot track-dot-now legend-dot" /> Latest estimate
                </span>
                <span className="legend-item">
                  <span className="legend-swatch track-seg-slip" /> Slipped
                </span>
                <span className="legend-item">
                  <span className="legend-swatch track-seg-late" /> Overdue
                </span>
              </p>
            </>
          )}
        </main>

        {panelOpen && (
          <aside
            className="panel"
            aria-label={panel.mode === "new" ? "Add pledge" : panel.mode === "inbox" ? "Email" : "Pledge details"}
          >
            {panel.mode === "inbox" && (
              <InboxPanel
                projects={all}
                onClose={() => setPanel({ mode: "none" })}
                onChanged={() => void refresh()}
                onOpenProject={(id) => setPanel({ mode: "detail", id })}
                onNewPledge={(message) => setPanel({ mode: "new", from: message })}
              />
            )}
            {panel.mode === "new" && (
              <div className="panel-body">
                <PanelBar
                  title={panel.from ? "New pledge from email" : "Add pledge"}
                  onClose={() => setPanel(panel.from ? { mode: "inbox" } : { mode: "none" })}
                />
                {panel.from && (
                  <p className="hint">
                    From “{panel.from.subject}”. Check the name, then save: the email goes onto the new pledge's
                    timeline.
                  </p>
                )}
                <ProjectForm
                  key={panel.from?.id ?? "blank"}
                  initial={panel.from ? draftFrom(panel.from) : EMPTY_PROJECT}
                  submitLabel="Add pledge"
                  onCancel={() => setPanel(panel.from ? { mode: "inbox" } : { mode: "none" })}
                  askRewards
                  onSubmit={async (input, rewards) => {
                    const created = await api.createProject({ ...input, rewards });
                    if (panel.from) await api.assignMessage(panel.from.id, created.id);
                    await refresh();
                    setView("all");
                    setPlatform(null);
                    setPanel({ mode: "detail", id: created.id });
                  }}
                />
              </div>
            )}
            {panel.mode === "detail" && (
              <ProjectPanel
                projectId={panel.id}
                onClose={() => setPanel({ mode: "none" })}
                onChanged={() => void refresh()}
                onDeleted={() => {
                  setPanel({ mode: "none" });
                  void refresh();
                }}
              />
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
