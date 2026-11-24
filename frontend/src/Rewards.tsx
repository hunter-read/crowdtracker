import { useState, type FormEvent } from "react";
import { api } from "./api";
import { Icon } from "./Icon";
import type { ProjectDetail, RewardKind } from "./types";
import { REWARD_KIND_LABEL } from "./vocab";

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * The parts of a pledge that arrive separately: a PDF, a hardcover, a wave of
 * add-ons. Receiving some moves the pledge to "Partly received"; receiving all
 * of them moves it to "Received".
 */
export function Rewards({
  project,
  busy,
  run,
  onUpdated,
}: {
  project: ProjectDetail;
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  onUpdated: (p: ProjectDetail) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<RewardKind>("physical");

  const save = (action: () => Promise<ProjectDetail>) =>
    run(async () => {
      onUpdated(await action());
    });

  function add(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    void save(async () => {
      const updated = await api.addReward(project.id, { name: name.trim(), kind, received_on: null });
      setName("");
      return updated;
    });
  }

  const total = project.rewards.length;

  return (
    <section className="panel-section" aria-labelledby="rewards-heading">
      <div className="section-head">
        <h3 id="rewards-heading">Rewards</h3>
        {total > 0 && (
          <span className="hint num">
            {project.rewards_received} of {total} received
          </span>
        )}
      </div>

      {total === 0 ? (
        <p className="empty-inline">
          List the parts of this pledge that arrive separately (a PDF, a hardcover, add-ons) to track each one.
        </p>
      ) : (
        <ul className="rewards">
          {project.rewards.map((r) => (
            <li key={r.id} className={r.received_on ? "reward reward-in" : "reward"}>
              <div className="reward-main">
                <span className="reward-name">{r.name}</span>
                <span className="reward-kind">{REWARD_KIND_LABEL[r.kind]}</span>
              </div>
              {r.received_on ? (
                <label className="reward-date">
                  <span className="visually-hidden">{r.name} received on</span>
                  <Icon name="check" size={14} />
                  <input
                    type="date"
                    value={r.received_on}
                    disabled={busy}
                    onChange={(e) =>
                      void save(() => api.updateReward(r.id, { received_on: e.target.value || null }))
                    }
                  />
                </label>
              ) : (
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={busy}
                  onClick={() => void save(() => api.updateReward(r.id, { received_on: todayIso() }))}
                >
                  Received
                </button>
              )}
              <button
                type="button"
                className="icon-button"
                aria-label={`Remove reward: ${r.name}`}
                disabled={busy}
                onClick={() => void save(() => api.deleteReward(r.id))}
              >
                <Icon name="close" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="reward-add" onSubmit={add}>
        <label className="field">
          <span className="field-label">Add a reward</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Hardcover"
            maxLength={200}
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span className="field-label">Type</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as RewardKind)}>
            <option value="physical">Physical</option>
            <option value="digital">Digital</option>
          </select>
        </label>
        <button type="submit" className="btn" disabled={busy || !name.trim()}>
          Add
        </button>
      </form>
    </section>
  );
}
