#!/usr/bin/env bash
# Amorce un Pod Runpod Ubuntu standard (sans notre image) pour tester une branche rapidement.
#   curl -fsSL https://raw.githubusercontent.com/Matt95354855/phone_emulator/<branche>/scripts/bootstrap_dev_pod.sh | bash -s -- <branche>
# Étapes : diagnostic → dépendances → code → SDK Android (si licences acceptées) → service en arrière-plan.
set -euo pipefail
BRANCH="${1:-main}"
APP=/workspace/phone_emulator-src
export PE_DATA_DIR=/workspace/phone_emulator
export PE_ANDROID_SDK_ROOT=/workspace/android-sdk ANDROID_SDK_ROOT=/workspace/android-sdk
export PATH="$PE_ANDROID_SDK_ROOT/platform-tools:$PE_ANDROID_SDK_ROOT/emulator:$HOME/.local/bin:$PATH"
export PE_ADB_PATH="$PE_ANDROID_SDK_ROOT/platform-tools/adb"

echo "== Dépendances système"
apt-get update -qq
apt-get install -y -qq --no-install-recommends git curl unzip ca-certificates openjdk-17-jre-headless \
  libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libxdamage1 libxrandr2 \
  libxkbfile1 libasound2 libdbus-1-3 libfontconfig1 libx11-6 libxext6 >/dev/null
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.5.4/install.sh | sh >/dev/null
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null && apt-get install -y -qq nodejs >/dev/null; }

echo "== Code ($BRANCH)"
if [[ -d $APP/.git ]]; then git -C $APP fetch -q origin "$BRANCH" && git -C $APP checkout -q -B "$BRANCH" "origin/$BRANCH"
else git clone -q --branch "$BRANCH" https://github.com/Matt95354855/phone_emulator.git $APP; fi
cd $APP
bash scripts/runpod_diag.sh >/dev/null 2>&1 || true
echo "   rapport de diagnostic : /diag/report.txt"
uv sync -q --frozen --no-dev
(cd apps/web && npm ci --silent --no-audit --no-fund && npm run build --silent)

echo "== SDK Android"
bash scripts/install_android_sdk.sh || echo "   (SDK non installé : relancer avec PE_ACCEPT_ANDROID_SDK_LICENSES=1)"

echo "== Contrôle préalable"
bash scripts/preflight.sh || true

if [[ -z "${PE_ACCESS_TOKEN:-}" ]]; then
  export PE_ACCESS_TOKEN=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
  echo "$PE_ACCESS_TOKEN" > /workspace/.pe_access_token && chmod 600 /workspace/.pe_access_token
  echo "   jeton d'accès généré : /workspace/.pe_access_token"
fi
export PE_WEB_DIST=$APP/apps/web/dist PE_DEVICE_BACKEND="${PE_DEVICE_BACKEND:-emulator}"
mkdir -p $PE_DATA_DIR/logs
nohup uv run --no-sync phone-emulator > $PE_DATA_DIR/logs/control.log 2>&1 &
echo "== Service lancé (PID $!) sur le port 8000 — journal : $PE_DATA_DIR/logs/control.log"
