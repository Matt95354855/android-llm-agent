import { useEffect, useState } from "react";
import type { AppEvent, Device } from "../api";

const MAX_EVENTS = 300;

export function useEvents(onEvent: (e: AppEvent) => void) {
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    // EventSource renvoie Last-Event-ID à la reconnexion : pas de trou ni de doublon (U05).
    const es = new EventSource("/api/events", { withCredentials: true });
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = () => undefined;
    const handler = (msg: MessageEvent) => onEvent(JSON.parse(msg.data) as AppEvent);
    const types = [
      "system.started", "system.recovery", "device.state", "device.control", "action.manual",
      "mission.created", "mission.paused", "mission.queued", "mission.cancelled", "mission.running",
      "mission.succeeded", "mission.failed", "apk.added", "apk.install",
    ];
    types.forEach((t) => es.addEventListener(t, handler));
    return () => es.close();
  }, [onEvent]);
  return connected;
}

export function ActivityPanel({ events, devices }: { events: AppEvent[]; devices: Device[] }) {
  const [filter, setFilter] = useState<string>("");
  const shown = events.filter((e) => !filter || e.device_id === filter).slice(-MAX_EVENTS).reverse();
  return (
    <div className="section">
      <h2>Activité</h2>
      <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtrer par téléphone">
        <option value="">Tous les téléphones</option>
        {devices.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <div className="events" style={{ marginTop: 10 }}>
        {shown.length === 0 && <p className="muted small">Aucun événement.</p>}
        {shown.map((e) => (
          <div key={e.id} className={`event ${e.type.split(".")[0]} ${e.type.includes("error") ? "error" : ""}`}>
            <time>{new Date(e.ts).toLocaleTimeString("fr-FR")}</time>
            {e.summary}
          </div>
        ))}
      </div>
    </div>
  );
}
