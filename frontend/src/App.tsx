import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import { Icon } from "./Icon";
import { EMPTY_PROJECT, ProjectForm } from "./ProjectForm";
import { ListSkeleton, ProjectList, type Sort, type SortKey } from "./ProjectList";
import { PanelBar, ProjectPanel } from "./ProjectPanel";
import { buildAxis } from "./SlipTrack";
import type { Platform, Project } from "./types";
import { CLOSED, PLATFORMS, PLATFORM_LABEL, STAGES } from "./vocab";

type View = "open" | "overdue" | "action" | "closed" | "all";

const VIEWS: { id: View; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "overdue", label: "Overdue" },
  { id: "action", label: "Needs you" },
  { id: "closed", label: "Closed" },
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
    case "closed":
      return CLOSED.includes(p.stage);
    default:
      return true;
  }
};

const EMPTY_VIEW: Record<View, string> = {
  open: "No open pledges. Everything you've backed has been delivered or cancelled.",
  overdue: "Nothing is overdue. Every open pledge is still inside its latest estimate.",
  action: "Nothing is waiting on you. Pledges show up here while a survey is open.",
  closed: "No closed pledges yet. Delivered and cancelled pledges collect here.",
  all: "",
};

type PanelState = { mode: "none" } | { mode: "new" } | { mode: "detail"; id: number };

export default function App() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("open");
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [sort, setSort] = useState<Sort>({ key: "estimate", dir: 1 });
  const [panel, setPanel] = useState<PanelState>({ mode: "none" });

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.listProjects());
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
    return [...rows].sort((a, b) => cmp[sort.key](a, b) * sort.dir);
  }, [viewed, platform, sort]);

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
        <button type="button" className="btn btn-on-ink" onClick={() => setPanel({ mode: "new" })}>
          <Icon name="plus" /> Add pledge
        </button>
      </header>

      <div className="layout">
        <main className="main">
          <h1 className="visually-hidden">Pledges</h1>

          <nav className="views" aria-label="Views">
            {VIEWS.map((v) => (
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
          <aside className="panel" aria-label={panel.mode === "new" ? "Add pledge" : "Pledge details"}>
            {panel.mode === "new" && (
              <div className="panel-body">
                <PanelBar title="Add pledge" onClose={() => setPanel({ mode: "none" })} />
                <ProjectForm
                  initial={EMPTY_PROJECT}
                  submitLabel="Add pledge"
                  onCancel={() => setPanel({ mode: "none" })}
                  onSubmit={async (input) => {
                    const created = await api.createProject(input);
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
