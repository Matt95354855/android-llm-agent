import { useEffect, useState } from "react";
import { api, ApiError, MISSION_STATUS_LABEL, type Device, type Mission } from "../api";

const DRAFT_KEY = "pe.mission.draft";
const ACTIVE = new Set(["queued", "running", "paused", "waiting_user", "recovering"]);

function loadDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

export function MissionPanel({ devices, missions, onChanged }: {
  devices: Device[];
  missions: Mission[];
  onChanged: () => void;
}) {
  const [mode, setMode] = useState<"independent" | "coordinated">("independent");
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState(loadDraft);
  const [perDevice, setPerDevice] = useState(false);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (selected.length === 0 && devices.length) setSelected(devices.map((d) => d.id));
  }, [devices, selected.length]);

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, prompt);
    } catch {
      /* stockage indisponible : le brouillon n'est simplement pas conservé */
    }
  }, [prompt]);

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].sort()));

  const submit = async () => {
    setError(null);
    setSending(true);
    try {
      const body =
        mode === "independent" && perDevice
          ? { mode, device_ids: selected, tasks: selected.map((d) => ({ device_id: d, prompt: prompts[d] ?? "" })) }
          : { mode, device_ids: selected, prompt };
      await api.createMission({ ...body, client_request_id: crypto.randomUUID() });
      setPrompt("");
      setPrompts({});
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const canSend =
    selected.length > 0 &&
    !sending &&
    (mode === "independent" && perDevice ? selected.every((d) => (prompts[d] ?? "").trim()) : prompt.trim());

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && canSend) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <>
      <div className="section">
        <h2>Nouvelle mission</h2>
        <div className="segmented" role="tablist" aria-label="Mode de mission">
          <button className={mode === "independent" ? "active" : ""} onClick={() => setMode("independent")}>
            Indépendante
          </button>
          <button className={mode === "coordinated" ? "active" : ""} onClick={() => setMode("coordinated")}>
            Coordonnée
          </button>
        </div>
        <p className="muted small">
          {mode === "independent"
            ? "Chaque téléphone poursuit sa propre mission, avec son historique et son résultat."
            : "Un objectif commun est découpé en sous-tâches réparties entre les téléphones choisis."}
        </p>
        <div className="devices-pick" role="group" aria-label="Téléphones ciblés">
          {devices.map((d) => (
            <label key={d.id}>
              <input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} />
              {d.name}
            </label>
          ))}
        </div>
        {mode === "independent" && (
          <label className="small muted row" style={{ gap: 6 }}>
            <input type="checkbox" style={{ flex: "0 0 auto", width: "auto" }} checked={perDevice}
              onChange={(e) => setPerDevice(e.target.checked)} />
            <span>Un prompt différent par téléphone</span>
          </label>
        )}
        {mode === "independent" && perDevice ? (
          selected.map((d) => (
            <div key={d} style={{ marginTop: 8 }}>
              <div className="small muted">{devices.find((x) => x.id === d)?.name}</div>
              <textarea value={prompts[d] ?? ""} onKeyDown={onKey} style={{ minHeight: 64 }}
                onChange={(e) => setPrompts((p) => ({ ...p, [d]: e.target.value }))} />
            </div>
          ))
        ) : (
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={onKey}
            placeholder={mode === "independent" ? "Décrivez ce que chaque téléphone doit faire…" : "Décrivez l'objectif commun…"}
            aria-label="Prompt de mission"
            style={{ marginTop: 8 }}
          />
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <span className="small muted">Ctrl + Entrée pour lancer</span>
          <button className="primary" style={{ flex: "0 0 auto" }} disabled={!canSend} onClick={submit}>
            Lancer
          </button>
        </div>
        {error && <div className="error-text">{error}</div>}
      </div>

      <div className="section">
        <h2>Missions</h2>
        {missions.length === 0 && <p className="muted small">Aucune mission pour l'instant.</p>}
        <div className="list">
          {missions.map((m) => (
            <div className="card" key={m.id}>
              <div className="title">{m.title}</div>
              <div className="small muted">
                {m.mode === "independent" ? "Indépendante" : "Coordonnée"} · {MISSION_STATUS_LABEL[m.status]} ·{" "}
                {m.device_ids.length} téléphone(s)
              </div>
              {m.runs.some((r) => r.wait_reason) && (
                <div className="small muted">{m.runs.find((r) => r.wait_reason)?.wait_reason}</div>
              )}
              {ACTIVE.has(m.status) && (
                <div className="actions">
                  {m.status !== "paused" ? (
                    <button onClick={() => api.missionAction(m.id, "pause").then(onChanged)}>Pause</button>
                  ) : (
                    <button onClick={() => api.missionAction(m.id, "resume").then(onChanged)}>Reprendre</button>
                  )}
                  <button className="danger" onClick={() => api.missionAction(m.id, "cancel").then(onChanged)}>
                    Arrêter
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
