export type Platform =
  | "kickstarter"
  | "backerkit"
  | "gamefound"
  | "pledgemanager"
  | "indiegogo"
  | "other";

export type Stage =
  | "live"
  | "funded"
  | "survey_open"
  | "survey_done"
  | "charged"
  | "address_locked"
  | "shipping"
  | "delivered"
  | "cancelled";

export type EventKind =
  | "update"
  | "survey"
  | "charge"
  | "address_lock"
  | "shipping"
  | "delivery"
  | "estimate_change"
  | "stage_change"
  | "note";

export interface ProjectInput {
  name: string;
  category: string | null;
  creator: string | null;
  funded_on: Platform;
  pledge_manager: Platform | null;
  campaign_url: string | null;
  pledge_manager_url: string | null;
  tier: string | null;
  pledge_amount: number | null;
  currency: string;
  original_est: string | null;
  current_est: string | null;
  stage: Stage;
  notes: string | null;
}

export interface Project extends ProjectInput {
  id: number;
  created_at: string;
  updated_at: string;
  original_est_label: string | null;
  current_est_label: string | null;
  effective_est: string | null;
  effective_est_end: string | null;
  overdue: boolean;
  months_overdue: number;
  slip_months: number | null;
  needs_action: boolean;
  last_event_on: string | null;
  event_count: number;
}

export interface TimelineEvent {
  id: number;
  project_id: number;
  occurred_on: string;
  kind: EventKind;
  title: string;
  body: string | null;
  url: string | null;
  source: "manual" | "system" | "email";
  created_at: string;
}

export interface ProjectDetail extends Project {
  events: TimelineEvent[];
}

export interface EventInput {
  occurred_on: string | null;
  kind: EventKind;
  title: string;
  body: string | null;
  url: string | null;
}
