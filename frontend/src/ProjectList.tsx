import { Icon } from "./Icon";
import { AxisHeader, SlipTrack, describeSchedule, type Axis } from "./SlipTrack";
import type { Platform, Project } from "./types";
import { PLATFORM_LABEL, REWARD_KIND_LABEL, STAGE_LABEL, formatDay } from "./vocab";

export type SortKey = "estimate" | "name" | "stage";
export interface Sort {
  key: SortKey;
  dir: 1 | -1;
}

export function PlatformChip({ platform }: { platform: Platform }) {
  return <span className={`chip platform-${platform}`}>{PLATFORM_LABEL[platform]}</span>;
}

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  sort: Sort;
  onSort: (key: SortKey) => void;
}) {
  const active = sort.key === sortKey;
  return (
    <th scope="col" aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort" onClick={() => onSort(sortKey)}>
        {label}
        <span className={active ? "th-arrow th-arrow-on" : "th-arrow"}>
          <Icon name={active && sort.dir === -1 ? "sortDown" : "sortUp"} size={14} />
        </span>
      </button>
    </th>
  );
}

export function ProjectList({
  projects,
  axis,
  selectedId,
  sort,
  onSort,
  onSelect,
}: {
  projects: Project[];
  axis: Axis;
  selectedId: number | null;
  sort: Sort;
  onSort: (key: SortKey) => void;
  onSelect: (id: number) => void;
}) {
  return (
    <table className="pledges">
      <thead>
        <tr>
          <SortHeader label="Pledge" sortKey="name" sort={sort} onSort={onSort} />
          <th scope="col">Platform</th>
          <SortHeader label="Stage" sortKey="stage" sort={sort} onSort={onSort} />
          <SortHeader label="Estimate" sortKey="estimate" sort={sort} onSort={onSort} />
          <th scope="col" className="col-track">
            <AxisHeader axis={axis} />
          </th>
          <th scope="col">Schedule</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => {
          const schedule = describeSchedule(p);
          return (
            <tr
              key={p.id}
              className={p.id === selectedId ? "row row-selected" : "row"}
              onClick={() => onSelect(p.id)}
            >
              <th scope="row" className="cell-name">
                <button
                  type="button"
                  className="name-button"
                  aria-current={p.id === selectedId ? "true" : undefined}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect(p.id);
                  }}
                >
                  {p.name}
                </button>
                <span className="sub">{[p.category, p.creator].filter(Boolean).join(" · ") || "Uncategorised"}</span>
                {p.rewards.length > 0 && (
                  <span className="sub reward-summary">
                    {(["digital", "physical"] as const)
                      .filter((k) => p.rewards.some((r) => r.kind === k))
                      .map((k) => REWARD_KIND_LABEL[k])
                      .join(" + ")}
                    {" · "}
                    <span className="num">
                      {p.rewards_received}/{p.rewards.length}
                    </span>{" "}
                    in
                  </span>
                )}
              </th>
              <td className="cell-platform">
                <PlatformChip platform={p.funded_on} />
                {p.pledge_manager && p.pledge_manager !== p.funded_on && (
                  <span className="sub">Survey on {PLATFORM_LABEL[p.pledge_manager]}</span>
                )}
              </td>
              <td className="cell-stage">
                <span className={p.needs_action ? "stage stage-action" : "stage"}>{STAGE_LABEL[p.stage]}</span>
                {p.needs_action && <span className="sub sub-action">Waiting on you</span>}
              </td>
              <td className="cell-estimate">
                <span className="num">
                  {p.stage === "delivered" && p.received_on
                    ? formatDay(p.received_on)
                    : (p.current_est_label ?? p.original_est_label ?? "None")}
                </span>
                {p.stage === "delivered" && p.received_on && p.original_est_label ? (
                  <span className="sub num">promised {p.original_est_label}</span>
                ) : p.current_est_label && p.original_est_label && p.current_est !== p.original_est && (
                  <span className="sub num">was {p.original_est_label}</span>
                )}
              </td>
              <td className="cell-track">
                <SlipTrack project={p} axis={axis} />
              </td>
              <td className="cell-schedule">
                <span className={`schedule schedule-${schedule.tone}`}>{schedule.text}</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ListSkeleton() {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading pledges">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="skeleton-row">
          <span className="skeleton-bar" style={{ width: `${34 - (i % 3) * 6}%` }} />
          <span className="skeleton-bar" style={{ width: "12%" }} />
          <span className="skeleton-bar" style={{ width: "30%" }} />
        </div>
      ))}
    </div>
  );
}
