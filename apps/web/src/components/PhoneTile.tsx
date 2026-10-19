import { useEffect, useRef, useState } from "react";
import { api, ApiError, DEVICE_STATE_LABEL, type Device, type Mission } from "../api";

const STATE_CLASS: Record<string, string> = {
  ready: "ok", busy: "accent", manual: "manual", booting: "warn", offline: "danger", error: "danger", stopped: "",
};
const LIVE = new Set(["ready", "busy", "manual"]);

interface Props {
  device: Device;
  mission?: Mission;
  expanded: boolean;
  onToggleExpand: () => void;
  onChanged: () => void;
}

export function PhoneTile({ device, mission, expanded, onToggleExpand, onChanged }: Props) {
  const [src, setSrc] = useState<string | null>(null);
  const [takenAt, setTakenAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [visible, setVisible] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tileRef = useRef<HTMLElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragStart = useRef<{ x: number; y: number; t: number } | null>(null);
  const live = LIVE.has(device.state);
  const manual = device.controller === "user";

  // Ne rafraîchit que les tuiles visibles (K13).
  useEffect(() => {
    const el = tileRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (!live || !visible) return;
    let stopped = false;
    let currentUrl: string | null = null;
    const period = expanded || manual ? 400 : 900;
    const tick = async () => {
      while (!stopped) {
        const started = Date.now();
        try {
          const res = await fetch(`/api/devices/${device.id}/screen`, { credentials: "same-origin", cache: "no-store" });
          if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            if (currentUrl) URL.revokeObjectURL(currentUrl);
            currentUrl = url;
            if (!stopped) {
              setSrc(url);
              setTakenAt(Number(res.headers.get("X-Screen-Taken-At")) * 1000 || Date.now());
            }
          }
        } catch {
          /* le compteur d'âge signale l'absence de nouvelles images */
        }
        await new Promise((r) => setTimeout(r, Math.max(100, period - (Date.now() - started))));
      }
    };
    tick();
    return () => {
      stopped = true;
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [device.id, live, visible, expanded, manual]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const toDevice = (clientX: number, clientY: number) => {
    const img = imgRef.current!;
    const rect = img.getBoundingClientRect();
    const scaleX = img.naturalWidth / rect.width;
    const scaleY = img.naturalHeight / rect.height;
    return {
      x: Math.round(Math.min(Math.max(clientX - rect.left, 0), rect.width) * scaleX),
      y: Math.round(Math.min(Math.max(clientY - rect.top, 0), rect.height) * scaleY),
    };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!manual) return;
    dragStart.current = { ...toDevice(e.clientX, e.clientY), t: Date.now() };
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const start = dragStart.current;
    dragStart.current = null;
    if (!manual || !start) return;
    const end = toDevice(e.clientX, e.clientY);
    const dist = Math.hypot(end.x - start.x, end.y - start.y);
    const duration = Date.now() - start.t;
    const action =
      dist < 12
        ? duration > 600
          ? { tool: "long_press", x: start.x, y: start.y, duration_ms: Math.min(duration, 5000) }
          : { tool: "tap", x: start.x, y: start.y }
        : { tool: "swipe", x1: start.x, y1: start.y, x2: end.x, y2: end.y, duration_ms: Math.min(Math.max(duration, 80), 3000) };
    run(() => api.action(device.id, action));
  };

  const age = takenAt ? Math.max(0, (now - takenAt) / 1000) : null;
  const run_ = mission?.runs.find((r) => r.device_id === device.id);

  return (
    <section ref={tileRef} className={`tile ${manual ? "manual" : ""}`} aria-label={device.name}>
      <header>
        <span className="name" title={device.id}>{device.name}</span>
        <span className={`badge ${STATE_CLASS[device.state] ?? ""}`}>{DEVICE_STATE_LABEL[device.state]}</span>
        {device.backend === "demo" && <span className="badge demo" title="Appareil factice">Démo</span>}
        <span className="spacer" />
        <button onClick={onToggleExpand} aria-label={expanded ? "Revenir à la mosaïque" : "Agrandir"}>
          {expanded ? "Mosaïque" : "Agrandir"}
        </button>
      </header>
      <div
        className={`screen-wrap ${manual ? "interactive" : ""}`}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
      >
        {live && src ? (
          <>
            <img ref={imgRef} src={src} alt={`Écran de ${device.name}`} draggable={false} />
            {age !== null && (
              <span className={`age ${age > 3 ? "stale" : ""}`}>
                {age > 3 ? "Image figée · " : ""}il y a {age.toFixed(1).replace(".", ",")} s
              </span>
            )}
          </>
        ) : (
          <div className="screen-placeholder">
            {device.state === "booting" && "Android démarre…"}
            {device.state === "stopped" && "Téléphone arrêté"}
            {device.state === "offline" && "Connexion ADB perdue"}
            {device.state === "error" && (device.error ?? "Erreur")}
            {live && "Connexion à l'écran…"}
          </div>
        )}
      </div>
      {run_ && <div className="mission-line" title={run_.goal}>Mission : {run_.goal}</div>}
      <footer>
        {live && !manual && (
          <button onClick={() => run(() => api.takeControl(device.id))} disabled={device.controller !== "none"}>
            Prendre la main
          </button>
        )}
        {manual && (
          <>
            <button className="primary" onClick={() => run(() => api.releaseControl(device.id))}>Rendre la main</button>
            <button onClick={() => run(() => api.action(device.id, { tool: "key", key: "back" }))}>Retour</button>
            <button onClick={() => run(() => api.action(device.id, { tool: "key", key: "home" }))}>Accueil</button>
            <button onClick={() => run(() => api.action(device.id, { tool: "key", key: "recents" }))}>Récents</button>
            <ManualText deviceId={device.id} onError={setError} />
          </>
        )}
        {(device.state === "stopped" || device.state === "error") && (
          <button onClick={() => run(() => api.startDevice(device.id))}>Démarrer</button>
        )}
        {live && !manual && device.controller === "none" && (
          <button onClick={() => run(() => api.stopDevice(device.id))}>Éteindre</button>
        )}
      </footer>
      {error && <div className="error-text" style={{ padding: "0 10px 8px" }}>{error}</div>}
    </section>
  );
}

function ManualText({ deviceId, onError }: { deviceId: string; onError: (e: string | null) => void }) {
  const [text, setText] = useState("");
  return (
    <form
      className="row"
      style={{ flexBasis: "100%" }}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!text) return;
        try {
          await api.action(deviceId, { tool: "type_text", text });
          setText("");
          onError(null);
        } catch (err) {
          onError(err instanceof ApiError ? err.message : String(err));
        }
      }}
    >
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Saisir du texte sur le téléphone" />
      <button type="submit" style={{ flex: "0 0 auto" }}>Envoyer</button>
    </form>
  );
}
