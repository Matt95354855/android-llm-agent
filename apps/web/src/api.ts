export type DeviceState = "created" | "booting" | "ready" | "busy" | "manual" | "offline" | "error" | "stopped";
export type Controller = "none" | "agent" | "user" | "replay" | "system";
export type MissionStatus =
  | "queued" | "running" | "paused" | "waiting_user" | "recovering" | "succeeded" | "failed" | "cancelled";

export interface Device {
  id: string;
  name: string;
  backend: "emulator" | "demo";
  state: DeviceState;
  serial: string | null;
  controller: Controller;
  run_id: string | null;
  mission_id: string | null;
  egress_ip: string | null;
  egress_checked_at: string | null;
  compliant: boolean | null;
  last_seen_at: string | null;
  error: string | null;
}

export interface Run {
  id: string;
  device_id: string;
  goal: string;
  status: MissionStatus;
  outcome: string;
  summary: string | null;
  wait_reason: string | null;
  steps: number;
}

export interface Mission {
  id: string;
  title: string;
  mode: "independent" | "coordinated";
  prompt: string | null;
  device_ids: string[];
  status: MissionStatus;
  outcome: string;
  runs: Run[];
  created_at: string;
}

export interface AppEvent {
  id: number;
  ts: string;
  type: string;
  summary: string;
  mission_id: string | null;
  device_id: string | null;
  data: Record<string, unknown>;
}

export interface Apk {
  id: string;
  filename: string;
  size: number;
  abis: string[];
  arm_only: boolean;
  source_url: string | null;
  downloaded_at: string;
}

export interface Ready {
  backend: string;
  demo: boolean;
  devices_ready: number;
  devices_total: number;
  agent_connected: boolean;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { credentials: "same-origin", ...init, headers: { ...headers, ...init.headers } });
  if (!res.ok) {
    let code = "http_error";
    let message = `Erreur ${res.status}`;
    try {
      const body = await res.json();
      code = body.code ?? code;
      message = body.message ?? message;
    } catch {
      /* réponse non JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  login: (token: string) => post("/api/login", { token }),
  ready: () => call<Ready>("/api/ready"),
  devices: () => call<Device[]>("/api/devices"),
  startDevice: (id: string) => post(`/api/devices/${id}/start`),
  stopDevice: (id: string) => post(`/api/devices/${id}/stop`),
  checkEgress: (id: string) => post<Device>(`/api/devices/${id}/egress`),
  takeControl: (id: string) => post(`/api/devices/${id}/control`),
  releaseControl: (id: string) => call(`/api/devices/${id}/control`, { method: "DELETE" }),
  action: (id: string, action: Record<string, unknown>) => post(`/api/devices/${id}/actions`, action),
  missions: () => call<Mission[]>("/api/missions"),
  createMission: (body: unknown) => post<Mission>("/api/missions", body),
  missionAction: (id: string, verb: "pause" | "resume" | "cancel") => post<Mission>(`/api/missions/${id}/${verb}`),
  apks: () => call<Apk[]>("/api/apks"),
  uploadApk: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<Apk>("/api/apks/upload", { method: "POST", body: form });
  },
  downloadApk: (url: string) => post<Apk>("/api/apks/download", { url }),
  installApk: (id: string, deviceIds: string[]) =>
    post<Record<string, { status: string; message?: string }>>(`/api/apks/${id}/install`, { device_ids: deviceIds }),
};

export const DEVICE_STATE_LABEL: Record<DeviceState, string> = {
  created: "Créé",
  booting: "Démarrage…",
  ready: "Prêt",
  busy: "Agent actif",
  manual: "Contrôle manuel",
  offline: "Hors ligne",
  error: "Erreur",
  stopped: "Arrêté",
};

export const MISSION_STATUS_LABEL: Record<MissionStatus, string> = {
  queued: "En file",
  running: "En cours",
  paused: "En pause",
  waiting_user: "Attend votre réponse",
  recovering: "Reprise",
  succeeded: "Réussie",
  failed: "Échec",
  cancelled: "Annulée",
};
