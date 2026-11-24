import type { Project } from "./types";
import { CLOSED, months, periodEnd } from "./vocab";

export interface Axis {
  min: number;
  max: number;
  today: number;
  years: { label: string; at: number }[];
}

const DAY = 86_400_000;

/** One time axis shared by every row, so slips line up and can be compared at a glance. */
export function buildAxis(projects: Project[], today: number): Axis {
  const points = [today];
  for (const p of projects) {
    if (p.original_est) points.push(periodEnd(p.original_est));
    if (p.current_est) points.push(periodEnd(p.current_est));
  }
  const pad = 75 * DAY;
  const min = Math.min(...points) - pad;
  const max = Math.max(...points) + pad;
  const years: Axis["years"] = [];
  for (let y = new Date(min).getUTCFullYear(); y <= new Date(max).getUTCFullYear(); y++) {
    const at = Date.UTC(y, 0, 1);
    if (at >= min && at <= max) years.push({ label: String(y), at });
  }
  return { min, max, today, years };
}

export function axisPos(axis: Axis, t: number): string {
  const ratio = (t - axis.min) / (axis.max - axis.min);
  return `${(Math.min(1, Math.max(0, ratio)) * 100).toFixed(2)}%`;
}

export function describeSchedule(p: Project): { text: string; tone: "late" | "slip" | "ok" | "muted" } {
  if (p.stage === "delivered") return { text: "Delivered", tone: "ok" };
  if (p.stage === "cancelled") return { text: "Cancelled", tone: "muted" };
  if (p.overdue) return { text: `${months(p.months_overdue)} overdue`, tone: "late" };
  if (p.slip_months && p.slip_months > 0) return { text: `Slipped ${months(p.slip_months)}`, tone: "slip" };
  if (!p.effective_est) return { text: "No date yet", tone: "muted" };
  return { text: "On schedule", tone: "ok" };
}

export function AxisHeader({ axis }: { axis: Axis }) {
  return (
    <div className="axis" aria-hidden="true">
      {axis.years
        // A year label that would sit under the "Today" marker is dropped; its gridline stays.
        .filter((y) => Math.abs(y.at - axis.today) / (axis.max - axis.min) > 0.07)
        .map((y) => (
          <span key={y.label} className="axis-year" style={{ left: axisPos(axis, y.at) }}>
            {y.label}
          </span>
        ))}
      <span className="axis-today" style={{ left: axisPos(axis, axis.today) }}>
        Today
      </span>
    </div>
  );
}

export function SlipTrack({ project, axis }: { project: Project; axis: Axis }) {
  const original = project.original_est ? periodEnd(project.original_est) : null;
  const current = project.current_est ? periodEnd(project.current_est) : null;
  const effective = current ?? original;
  const closed = CLOSED.includes(project.stage);

  const parts: string[] = [];
  if (project.original_est_label) parts.push(`promised ${project.original_est_label}`);
  if (project.current_est_label) parts.push(`now expected ${project.current_est_label}`);
  parts.push(describeSchedule(project).text.toLowerCase());

  return (
    <div className={`track${closed ? " track-closed" : ""}`} role="img" aria-label={parts.join(", ")}>
      {axis.years.map((y) => (
        <span key={y.label} className="track-grid" style={{ left: axisPos(axis, y.at) }} />
      ))}
      <span className="track-line" />
      {original !== null && current !== null && current > original && (
        <span
          className="track-seg track-seg-slip"
          style={{ left: axisPos(axis, original), right: `calc(100% - ${axisPos(axis, current)})` }}
        />
      )}
      {project.overdue && effective !== null && (
        <span
          className="track-seg track-seg-late"
          style={{ left: axisPos(axis, effective), right: `calc(100% - ${axisPos(axis, axis.today)})` }}
        />
      )}
      <span className="track-today" style={{ left: axisPos(axis, axis.today) }} />
      {original !== null && current !== null && (
        <span className="track-dot track-dot-promised" style={{ left: axisPos(axis, original) }} />
      )}
      {effective !== null && (
        <span
          className={`track-dot track-dot-now platform-${project.funded_on}`}
          style={{ left: axisPos(axis, effective) }}
        />
      )}
    </div>
  );
}
