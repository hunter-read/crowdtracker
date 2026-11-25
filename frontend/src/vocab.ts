import type { EventKind, Platform, RewardKind, Stage } from "./types";

export const PLATFORMS: Platform[] = [
  "kickstarter",
  "backerkit",
  "gamefound",
  "pledgemanager",
  "pledgebox",
  "indiegogo",
  "other",
];

export const PLATFORM_LABEL: Record<Platform, string> = {
  kickstarter: "Kickstarter",
  backerkit: "BackerKit",
  gamefound: "Gamefound",
  pledgemanager: "PledgeManager",
  pledgebox: "PledgeBox",
  indiegogo: "Indiegogo",
  other: "Other",
};

export const STAGES: Stage[] = [
  "live",
  "funded",
  "survey_open",
  "survey_done",
  "charged",
  "address_locked",
  "shipping",
  "partial",
  "delivered",
  "cancelled",
];

export const STAGE_LABEL: Record<Stage, string> = {
  live: "Campaign live",
  funded: "Funded",
  survey_open: "Survey open",
  survey_done: "Survey done",
  charged: "Charged",
  address_locked: "Address locked",
  shipping: "Shipping",
  partial: "Partly received",
  delivered: "Received",
  cancelled: "Cancelled",
};

export const REWARD_KIND_LABEL: Record<RewardKind, string> = {
  digital: "Digital",
  physical: "Physical",
};

export const CLOSED: Stage[] = ["delivered", "cancelled"];

/** Kinds a person logs by hand. estimate_change and stage_change are written by the server. */
export const MANUAL_KINDS: EventKind[] = [
  "update",
  "survey",
  "charge",
  "address_lock",
  "shipping",
  "delivery",
  "note",
];

export const KIND_LABEL: Record<EventKind, string> = {
  update: "Creator update",
  survey: "Survey",
  charge: "Charge",
  address_lock: "Address lock",
  shipping: "Shipping",
  delivery: "Delivery",
  estimate_change: "Estimate",
  stage_change: "Stage",
  note: "Note",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-23" -> "Nov 23, 2026" without timezone drift. */
export function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

export function months(n: number): string {
  if (n >= 24) {
    const years = n / 12;
    return `${Number.isInteger(years) ? years : years.toFixed(1)} yr`;
  }
  return `${n} mo`;
}

export function money(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}

/** "2021-08-10" -> UTC timestamp for that day. */
export function dayToUtc(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Last day of an estimate period, as a UTC timestamp. Mirrors backend/app/periods.py. */
export function periodEnd(period: string): number {
  const quarter = /^(\d{4})-Q([1-4])$/.exec(period);
  if (quarter) return Date.UTC(Number(quarter[1]), Number(quarter[2]) * 3, 0);
  const parts = period.split("-").map(Number);
  if (parts.length === 1) return Date.UTC(parts[0], 12, 0);
  if (parts.length === 2) return Date.UTC(parts[0], parts[1], 0);
  return Date.UTC(parts[0], parts[1] - 1, parts[2]);
}
