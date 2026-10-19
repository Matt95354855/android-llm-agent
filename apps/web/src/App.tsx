import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type AppEvent, type Device, type Mission, type Ready } from "./api";
import { ActivityPanel, useEvents } from "./components/ActivityPanel";
import { ApkPanel } from "./components/ApkPanel";
import { MissionPanel } from "./components/MissionPanel";
import { PhoneTile } from "./components/PhoneTile";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [ready, setReady] = useState<Ready | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [lostServer, setLostServer] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [r, d, m] = await Promise.all([api.ready(), api.devices(), api.missions()]);
      setReady(r);
      setDevices(d);
      setMissions(m);
      setAuthed(true);
      setLostServer(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAuthed(false);
      else setLostServer(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const onEvent = useCallback(
    (e: AppEvent) => {
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev.slice(-499), e]));
      if (e.type.startsWith("device.") || e.type.startsWith("mission.")) refresh();
    },
    [refresh],
  );

  if (authed === false) return <Login onDone={refresh} />;
  if (authed === null) return <div className="login muted">Connexion au service…</div>;

  return (
    <div className="layout">
      <div>
        <div className="topbar">
          <h1>phone_emulator</h1>
          {ready?.demo && <span className="badge demo">Mode démo : appareils factices</span>}
          <span className={`badge ${ready && ready.devices_ready === ready.devices_total ? "ok" : "warn"}`}>
            {ready ? `${ready.devices_ready}/${ready.devices_total} téléphones prêts` : "…"}
          </span>
          <span className={`badge ${ready?.agent_connected ? "ok" : "warn"}`}>
            {ready?.agent_connected ? "Agent connecté" : "Agent pas encore branché"}
          </span>
          <EventsBadge onEvent={onEvent} />
          <span className="spacer" />
          <button
            className="danger"
            onClick={async () => {
              const active = missions.filter((m) => !["succeeded", "failed", "cancelled"].includes(m.status));
              await Promise.allSettled(active.map((m) => api.missionAction(m.id, "cancel")));
              refresh();
            }}
          >
            Tout arrêter
          </button>
        </div>
        {lostServer && (
          <div className="banner danger">Service injoignable : nouvelle tentative automatique. Vos missions sont conservées côté serveur.</div>
        )}
      </div>
      <div className="main">
        <aside className="side">
          <MissionPanel devices={devices} missions={missions} onChanged={refresh} />
          <ApkPanel devices={devices} />
        </aside>
        <main className={`wall ${expanded ? "single" : ""}`}>
          {devices.length === 0 && <p className="muted">Aucun téléphone configuré.</p>}
          {devices
            .filter((d) => !expanded || d.id === expanded)
            .map((d) => (
              <PhoneTile
                key={d.id}
                device={d}
                mission={missions.find((m) => m.id === d.mission_id || (m.runs.some((r) => r.device_id === d.id) && !["succeeded", "failed", "cancelled"].includes(m.status)))}
                expanded={expanded === d.id}
                onToggleExpand={() => setExpanded((x) => (x === d.id ? null : d.id))}
                onChanged={refresh}
              />
            ))}
        </main>
        <aside className="side right">
          <ActivityPanel events={events} devices={devices} />
        </aside>
      </div>
    </div>
  );
}

function EventsBadge({ onEvent }: { onEvent: (e: AppEvent) => void }) {
  const connected = useEvents(onEvent);
  return <span className={`badge ${connected ? "ok" : "danger"}`}>{connected ? "Direct" : "Reconnexion…"}</span>;
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="login">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.login(token);
            onDone();
          } catch (err) {
            setError(err instanceof ApiError ? err.message : String(err));
          }
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18 }}>Connexion</h1>
        <p className="muted small" style={{ margin: 0 }}>Saisissez le jeton d'accès défini sur le serveur.</p>
        <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus aria-label="Jeton d'accès" />
        <button className="primary" type="submit" disabled={!token}>Se connecter</button>
        {error && <div className="error-text">{error}</div>}
      </form>
    </div>
  );
}
