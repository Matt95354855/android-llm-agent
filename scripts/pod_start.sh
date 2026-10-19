#!/usr/bin/env bash
# Point d'entrée du Pod : SSH (clé fournie par Runpod), contrôles préalables, puis service de contrôle.
set -euo pipefail

if [[ -n "${PUBLIC_KEY:-}" ]]; then
  mkdir -p ~/.ssh && chmod 700 ~/.ssh
  echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
  ssh-keygen -A >/dev/null
  /usr/sbin/sshd -o PasswordAuthentication=no
fi

mkdir -p "$PE_DATA_DIR"
echo "[pod] SDK Android"
/app/scripts/install_android_sdk.sh || echo "[pod] SDK Android non installé : les téléphones ne pourront pas démarrer"
echo "[pod] diagnostic préalable"
/app/scripts/preflight.sh || echo "[pod] des prérequis manquent : voir ci-dessus (le service démarre quand même pour le diagnostic)"

if [[ -z "${PE_ACCESS_TOKEN:-}" ]]; then
  echo "[pod] PE_ACCESS_TOKEN absent : le service refusera de démarrer." >&2
fi

cd /app
exec uv run --no-sync phone-emulator
