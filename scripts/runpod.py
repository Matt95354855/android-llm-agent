#!/usr/bin/env python3
"""Pilotage Runpod minimal avec garde-fous de dépense (X01).

Clé : variable RUNPOD_API_KEY ou fichier ~/.runpod/api_key (jamais dans le dépôt).

    uv run scripts/runpod.py status
    uv run scripts/runpod.py create --template infra/runpod/template-pod.json --cpu cpu5c --max-hourly 0.40
    uv run scripts/runpod.py create --template infra/runpod/template-model.json --gpu "NVIDIA A40" --max-hourly 0.60
    uv run scripts/runpod.py stop <pod_id>        # arrête le calcul, conserve le volume (facturé)
    uv run scripts/runpod.py terminate <pod_id> --yes   # supprime le Pod ET son volume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REST = "https://rest.runpod.io/v1"
GRAPHQL = "https://api.runpod.io/graphql"
MIN_BALANCE_USD = 2.0  # réserve conservée sur le compte


def api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY") or ""
    path = Path.home() / ".runpod" / "api_key"
    if not key and path.exists():
        key = path.read_text().strip()
    if not key:
        sys.exit("Clé Runpod introuvable : définir RUNPOD_API_KEY ou ~/.runpod/api_key")
    return key


def client() -> httpx.Client:
    return httpx.Client(headers={"Authorization": f"Bearer {api_key()}"}, timeout=30)


def account(c: httpx.Client) -> dict:
    r = c.post(GRAPHQL, json={"query": "query { myself { clientBalance currentSpendPerHr } }"})
    r.raise_for_status()
    return r.json()["data"]["myself"]


def status(c: httpx.Client, _: argparse.Namespace) -> None:
    acc = account(c)
    print(f"Solde : {acc['clientBalance']:.2f} $ · dépense actuelle : {acc['currentSpendPerHr']:.3f} $/h")
    pods = c.get(f"{REST}/pods").json()
    if not pods:
        print("Aucun Pod.")
    for p in pods:
        print(
            f"- {p['id']}  {p.get('name')}  {p.get('desiredStatus')}  {p.get('costPerHr')} $/h  {p.get('imageName')}"
        )


def create(c: httpx.Client, a: argparse.Namespace) -> None:
    acc = account(c)
    if acc["clientBalance"] - MIN_BALANCE_USD < a.max_hourly:
        sys.exit(
            f"Solde insuffisant ({acc['clientBalance']:.2f} $) pour garder {MIN_BALANCE_USD} $ de réserve."
        )
    tpl = json.loads(Path(a.template).read_text())
    if any("À_" in json.dumps(v) for v in tpl.values()):
        sys.exit("Ce template contient encore des valeurs « À_ÉPINGLER » : complétez-le avant de déployer.")
    body = {
        k: tpl[k]
        for k in (
            "imageName",
            "ports",
            "env",
            "containerDiskInGb",
            "volumeInGb",
            "volumeMountPath",
            "dockerStartCmd",
        )
        if k in tpl
    }
    body["name"] = a.name or tpl["name"]
    body["cloudType"] = a.cloud
    if a.cpu:
        body |= {"computeType": "CPU", "cpuFlavorIds": [a.cpu]}
    else:
        body |= {"computeType": "GPU", "gpuTypeIds": [a.gpu], "gpuCount": 1}
    r = c.post(f"{REST}/pods", json=body)
    if r.status_code >= 400:
        sys.exit(f"Création refusée ({r.status_code}) : {r.text[:500]}")
    pod = r.json()
    cost = float(pod.get("costPerHr") or 0)
    if cost > a.max_hourly:
        c.delete(f"{REST}/pods/{pod['id']}")
        sys.exit(f"Pod supprimé : {cost} $/h dépasse le plafond {a.max_hourly} $/h.")
    print(
        f"Pod {pod['id']} créé à {cost} $/h. Pensez à l'arrêter : uv run scripts/runpod.py stop {pod['id']}"
    )


def stop(c: httpx.Client, a: argparse.Namespace) -> None:
    c.post(f"{REST}/pods/{a.pod_id}/stop").raise_for_status()
    print("Pod arrêté. Le volume reste facturé tant que le Pod n'est pas supprimé.")


def start(c: httpx.Client, a: argparse.Namespace) -> None:
    c.post(f"{REST}/pods/{a.pod_id}/start").raise_for_status()
    print("Pod redémarré.")


def terminate(c: httpx.Client, a: argparse.Namespace) -> None:
    if not a.yes:
        sys.exit("Suppression définitive du Pod et de son volume : relancer avec --yes pour confirmer.")
    c.delete(f"{REST}/pods/{a.pod_id}").raise_for_status()
    print("Pod supprimé.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=status)
    cr = sub.add_parser("create")
    cr.add_argument("--template", required=True)
    cr.add_argument("--name")
    g = cr.add_mutually_exclusive_group(required=True)
    g.add_argument("--cpu", help="cpu3c, cpu3g, cpu3m, cpu5c, cpu5g, cpu5m")
    g.add_argument("--gpu", help='ex. "NVIDIA A40"')
    cr.add_argument("--cloud", default="SECURE", choices=["SECURE", "COMMUNITY"])
    cr.add_argument(
        "--max-hourly", type=float, required=True, help="plafond en $/h, le Pod est supprimé au-delà"
    )
    cr.set_defaults(fn=create)
    for name, fn in (("stop", stop), ("start", start), ("terminate", terminate)):
        sp = sub.add_parser(name)
        sp.add_argument("pod_id")
        if name == "terminate":
            sp.add_argument("--yes", action="store_true")
        sp.set_defaults(fn=fn)
    a = p.parse_args()
    with client() as c:
        a.fn(c, a)


if __name__ == "__main__":
    main()
