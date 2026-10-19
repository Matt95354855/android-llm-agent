import { useEffect, useState } from "react";
import { api, ApiError, type Apk, type Device } from "../api";

const fmtSize = (n: number) => `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Mo`;

export function ApkPanel({ devices }: { devices: Device[] }) {
  const [apks, setApks] = useState<Apk[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => api.apks().then(setApks).catch(() => undefined);
  useEffect(() => {
    refresh();
  }, []);

  const guard = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const install = (apk: Apk) =>
    guard(async () => {
      const targets = devices.filter((d) => ["ready"].includes(d.state)).map((d) => d.id);
      const res = await api.installApk(apk.id, targets);
      setMessage(
        Object.entries(res)
          .map(([d, r]) => `${devices.find((x) => x.id === d)?.name ?? d} : ${r.status === "done" ? "installé" : r.message ?? r.status}`)
          .join(" · "),
      );
    });

  return (
    <div className="section">
      <h2>Bibliothèque d'APK</h2>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          if (url) guard(() => api.downloadApk(url).then(() => setUrl("")));
        }}
      >
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="URL d'un APK" type="url" />
        <button type="submit" disabled={busy || !url} style={{ flex: "0 0 auto" }}>Télécharger</button>
      </form>
      <label className="small muted" style={{ display: "block", marginTop: 8 }}>
        ou importer un fichier
        <input type="file" accept=".apk" disabled={busy}
          onChange={(e) => e.target.files?.[0] && guard(() => api.uploadApk(e.target.files![0]))} />
      </label>
      {busy && <p className="small muted">Traitement…</p>}
      {message && <p className="small">{message}</p>}
      {error && <div className="error-text">{error}</div>}
      <div className="list" style={{ marginTop: 8 }}>
        {apks.map((a) => (
          <div className="card" key={a.id}>
            <div className="title">{a.filename}</div>
            <div className="small muted">
              {fmtSize(a.size)} · ABI : {a.abis.length ? a.abis.join(", ") : "aucune lib native"} · sha256 {a.id.slice(0, 10)}…
            </div>
            {a.arm_only && <div className="small muted">ARM uniquement : nécessite la traduction ARM de l'image Android.</div>}
            <div className="actions">
              <button disabled={busy} onClick={() => install(a)}>Installer sur les téléphones prêts</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
