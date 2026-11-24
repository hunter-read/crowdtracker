import type { EventInput, Project, ProjectDetail, ProjectInput, RewardInput, TimelineEvent } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: ["body", "field"], msg: "..."}]
    return detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc[d.loc.length - 1] : "";
        const msg = String(d?.msg ?? "invalid").replace(/^Value error, /, "");
        return field ? `${String(field).replace(/_/g, " ")}: ${msg}` : msg;
      })
      .join(". ");
  }
  return "Something went wrong.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the crowdtracker server. Check that it's running, then try again.", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(describe(body?.detail), res.status);
  return body as T;
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: number) => request<ProjectDetail>(`/projects/${id}`),
  createProject: (input: ProjectInput & { rewards?: RewardInput[] }) =>
    request<ProjectDetail>("/projects", { method: "POST", body: JSON.stringify(input) }),
  updateProject: (id: number, changes: Partial<ProjectInput>) =>
    request<ProjectDetail>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  addEvent: (id: number, input: EventInput) =>
    request<TimelineEvent>(`/projects/${id}/events`, { method: "POST", body: JSON.stringify(input) }),
  deleteEvent: (id: number) => request<void>(`/events/${id}`, { method: "DELETE" }),
  addReward: (projectId: number, input: RewardInput) =>
    request<ProjectDetail>(`/projects/${projectId}/rewards`, { method: "POST", body: JSON.stringify(input) }),
  updateReward: (id: number, changes: Partial<RewardInput>) =>
    request<ProjectDetail>(`/rewards/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteReward: (id: number) => request<ProjectDetail>(`/rewards/${id}`, { method: "DELETE" }),
};
