import { useState, type FormEvent } from "react";
import { ApiError } from "./api";
import type { Platform, ProjectInput, Stage } from "./types";
import { PLATFORMS, PLATFORM_LABEL, STAGES, STAGE_LABEL } from "./vocab";

export const EMPTY_PROJECT: ProjectInput = {
  name: "",
  category: null,
  creator: null,
  funded_on: "kickstarter",
  pledge_manager: null,
  campaign_url: null,
  pledge_manager_url: null,
  tier: null,
  pledge_amount: null,
  currency: "USD",
  original_est: null,
  current_est: null,
  stage: "funded",
  notes: null,
};

const PERIOD = /^\d{4}(-Q[1-4]|-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$/i;

export function periodError(value: string | null): string | null {
  if (!value || !value.trim()) return null;
  return PERIOD.test(value.trim()) ? null : "Use 2027, 2027-Q2, 2027-08 or 2027-08-15.";
}

/** Keep what was typed (spaces included) while editing; empty means "not set". */
const blank = (v: string): string | null => (v === "" ? null : v);

const TEXT_FIELDS = [
  "category",
  "creator",
  "tier",
  "campaign_url",
  "pledge_manager_url",
  "original_est",
  "current_est",
  "notes",
] as const;

function tidy(form: ProjectInput): ProjectInput {
  const out = { ...form };
  for (const key of TEXT_FIELDS) {
    const value = out[key]?.trim();
    out[key] = value ? value : null;
  }
  return out;
}

export function ProjectForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: ProjectInput;
  submitLabel: string;
  onSubmit: (input: ProjectInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<ProjectInput>(initial);
  const [amount, setAmount] = useState(initial.pledge_amount?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const originalError = periodError(form.original_est);
  const currentError = periodError(form.current_est);
  const amountError = amount.trim() !== "" && !(Number(amount) >= 0) ? "Enter a number, like 85 or 129.50." : null;
  const invalid = !form.name.trim() || !!originalError || !!currentError || !!amountError;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (invalid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        ...tidy(form),
        name: form.name.trim(),
        pledge_amount: amount.trim() === "" ? null : Number(amount),
        currency: (form.currency || "USD").toUpperCase(),
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save. Try again.");
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          required
          maxLength={200}
          autoFocus
          autoComplete="off"
        />
      </label>

      <div className="field-row">
        <label className="field">
          <span className="field-label">Category</span>
          <input
            value={form.category ?? ""}
            onChange={(e) => set("category", blank(e.target.value))}
            placeholder="TTRPG"
            maxLength={60}
            list="category-suggestions"
          />
          <datalist id="category-suggestions">
            <option value="TTRPG" />
            <option value="Board Game" />
            <option value="Video Game" />
            <option value="Books" />
            <option value="Device" />
          </datalist>
        </label>
        <label className="field">
          <span className="field-label">Creator</span>
          <input
            value={form.creator ?? ""}
            onChange={(e) => set("creator", blank(e.target.value))}
            maxLength={200}
            autoComplete="off"
          />
        </label>
      </div>

      <div className="field-row">
        <label className="field">
          <span className="field-label">Pledged on</span>
          <select value={form.funded_on} onChange={(e) => set("funded_on", e.target.value as Platform)}>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABEL[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Survey or pledge manager</span>
          <select
            value={form.pledge_manager ?? ""}
            onChange={(e) => set("pledge_manager", (e.target.value || null) as Platform | null)}
          >
            <option value="">Not announced</option>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABEL[p]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="field-row">
        <label className="field">
          <span className="field-label">Promised delivery</span>
          <input
            value={form.original_est ?? ""}
            onChange={(e) => set("original_est", blank(e.target.value))}
            placeholder="2027-08"
            aria-invalid={!!originalError}
            aria-describedby="hint-original"
            autoComplete="off"
          />
          <span id="hint-original" className={originalError ? "hint hint-error" : "hint"}>
            {originalError ?? "The date from the campaign page."}
          </span>
        </label>
        <label className="field">
          <span className="field-label">Now expected</span>
          <input
            value={form.current_est ?? ""}
            onChange={(e) => set("current_est", blank(e.target.value))}
            placeholder="2027-Q4"
            aria-invalid={!!currentError}
            aria-describedby="hint-current"
            autoComplete="off"
          />
          <span id="hint-current" className={currentError ? "hint hint-error" : "hint"}>
            {currentError ?? "Leave empty until the creator moves the date."}
          </span>
        </label>
      </div>

      <label className="field">
        <span className="field-label">Stage</span>
        <select value={form.stage} onChange={(e) => set("stage", e.target.value as Stage)}>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {STAGE_LABEL[s]}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span className="field-label">Reward tier</span>
        <input
          value={form.tier ?? ""}
          onChange={(e) => set("tier", blank(e.target.value))}
          maxLength={200}
          autoComplete="off"
        />
      </label>

      <div className="field-row field-row-amount">
        <label className="field">
          <span className="field-label">Amount pledged</span>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            aria-invalid={!!amountError}
            autoComplete="off"
          />
          {amountError && <span className="hint hint-error">{amountError}</span>}
        </label>
        <label className="field">
          <span className="field-label">Currency</span>
          <input
            value={form.currency}
            onChange={(e) => set("currency", e.target.value.toUpperCase().slice(0, 3))}
            maxLength={3}
            autoComplete="off"
          />
        </label>
      </div>

      <label className="field">
        <span className="field-label">Campaign link</span>
        <input
          type="url"
          value={form.campaign_url ?? ""}
          onChange={(e) => set("campaign_url", blank(e.target.value))}
          placeholder="https://"
        />
      </label>
      <label className="field">
        <span className="field-label">Pledge manager link</span>
        <input
          type="url"
          value={form.pledge_manager_url ?? ""}
          onChange={(e) => set("pledge_manager_url", blank(e.target.value))}
          placeholder="https://"
        />
      </label>

      <label className="field">
        <span className="field-label">Notes</span>
        <textarea value={form.notes ?? ""} onChange={(e) => set("notes", blank(e.target.value))} rows={3} />
      </label>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={invalid || saving}>
          {saving ? "Saving…" : submitLabel}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}
