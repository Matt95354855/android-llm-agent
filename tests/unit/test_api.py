import io
import time

import pytest
from fastapi.testclient import TestClient

from control.api import create_app


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def _login(c):
    assert c.post("/api/login", json={"token": "jeton-de-test"}).status_code == 200


def _wait_ready(c, n=4):
    for _ in range(50):
        devices = c.get("/api/devices").json()
        if sum(d["state"] == "ready" for d in devices) == n:
            return devices
        time.sleep(0.05)
    raise AssertionError(devices)


def test_requires_auth(client):
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/devices")
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert client.post("/api/login", json={"token": "faux"}).status_code == 401


def test_refuses_to_start_without_token(tmp_path):
    from control.config import Settings

    with pytest.raises(RuntimeError):
        create_app(Settings(data_dir=tmp_path))


def test_devices_screen_and_manual_control(client):
    _login(client)
    devices = _wait_ready(client)
    assert [d["id"] for d in devices] == ["tel-1", "tel-2", "tel-3", "tel-4"]
    r = client.get("/api/devices/tel-1/screen")
    assert r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")

    # sans contrôle, aucun geste n'est accepté
    assert (
        client.post("/api/devices/tel-1/actions", json={"tool": "tap", "x": 100, "y": 400}).status_code == 409
    )
    assert client.post("/api/devices/tel-1/control").status_code == 200
    r = client.post("/api/devices/tel-1/actions", json={"tool": "tap", "x": 100, "y": 400})
    assert r.status_code == 200 and r.json()["status"] == "done"
    obs = client.get("/api/devices/tel-1/observation").json()
    assert any(n["text"] == "Valeur : 1" for n in obs["ui_nodes"])
    # l'autre téléphone n'a reçu aucun geste
    obs2 = client.get("/api/devices/tel-2/observation").json()
    assert any(n["text"] == "Valeur : 0" for n in obs2["ui_nodes"])

    bad = client.post("/api/devices/tel-1/actions", json={"tool": "camera_on"})
    assert bad.status_code == 422
    assert client.delete("/api/devices/tel-1/control").status_code == 200


def test_mission_lifecycle_and_events(client):
    _login(client)
    body = {
        "mode": "independent",
        "device_ids": ["tel-1", "tel-3"],
        "tasks": [
            {"device_id": "tel-1", "prompt": "Ouvre les paramètres"},
            {"device_id": "tel-3", "prompt": "Ajoute une note « été »"},
        ],
        "client_request_id": "req-1",
    }
    m = client.post("/api/missions", json=body).json()
    assert m["status"] == "queued" and len(m["runs"]) == 2
    again = client.post("/api/missions", json=body).json()
    assert again["id"] == m["id"]  # déduplication

    assert client.post(f"/api/missions/{m['id']}/cancel").json()["status"] == "cancelled"
    r = client.post(f"/api/missions/{m['id']}/resume")
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"

    types = [e["type"] for e in client.get(f"/api/events/history?mission_id={m['id']}").json()]
    assert types == ["mission.created", "mission.cancelled"]


def test_mission_validation(client):
    _login(client)
    r = client.post("/api/missions", json={"mode": "independent", "device_ids": ["tel-9"], "prompt": "x"})
    assert r.json()["code"] == "unknown_device"
    r = client.post("/api/missions", json={"mode": "coordinated", "device_ids": ["tel-1"]})
    assert r.json()["code"] == "missing_prompt"


def test_apk_upload_rejects_html(client):
    _login(client)
    r = client.post("/api/apks/upload", files={"file": ("app.apk", io.BytesIO(b"<html>404</html>"))})
    assert r.status_code == 422 and r.json()["code"] == "apk_invalid"


def test_event_history_keeps_utc(client):
    _login(client)
    events = client.get("/api/events/history").json()
    assert events and all(e["ts"].endswith(("Z", "+00:00")) for e in events)
