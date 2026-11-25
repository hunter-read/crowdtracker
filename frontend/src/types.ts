export type Platform =
  | "kickstarter"
  | "backerkit"
  | "gamefound"
  | "pledgemanager"
  | "pledgebox"
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
  | "partial"
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

export type RewardKind = "digital" | "physical";

export interface RewardInput {
  name: string;
  kind: RewardKind;
  received_on: string | null;
}

export interface Reward extends RewardInput {
  id: number;
  project_id: number;
}

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
  campaign_ended: string | null;
  original_est: string | null;
  current_est: string | null;
  stage: Stage;
  received_on: string | null;
  notes: string | null;
  match_terms: string | null;
}

export interface Project extends ProjectInput {
  id: number;
  created_at: string;
  updated_at: string;
  original_est_label: string | null;
  current_est_label: string | null;
  months_since_campaign: number | null;
  months_late: number | null;
  rewards: Reward[];
  rewards_received: number;
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

export type InboxStatus = "matched" | "unsorted" | "ignored";

export interface InboxMessage {
  id: number;
  received_at: string;
  sender: string;
  subject: string;
  platform: Platform;
  kind: EventKind;
  stage_hint: Stage | null;
  url: string | null;
  tracking_url: string | null;
  campaign_url: string | null;
  excerpt: string | null;
  status: InboxStatus;
  match_reason: string | null;
  project_id: number | null;
  project_name: string | null;
  event_id: number | null;
}

export interface MailStatus {
  configured: boolean;
  host: string | null;
  folder: string | null;
  interval_minutes: number | null;
  unsorted: number;
  total: number;
  last_sync_at: string | null;
  last_error: string | null;
}

export interface SyncResult {
  ok: boolean;
  fetched: number;
  matched: number;
  unsorted: number;
  skipped: number;
  duplicate: number;
  error: string | null;
}
