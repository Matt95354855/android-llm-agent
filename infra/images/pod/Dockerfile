# Image Pod « Android + contrôle + interface » (W02, W04). Construite en CI, jamais dans le Pod.
# Le modèle Qwen tourne dans un Pod GPU séparé (voir infra/runpod/template-model.json).
# syntax=docker/dockerfile:1.7

FROM node:20.18.0-bookworm-slim AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM ubuntu:22.04 AS runtime
# Le SDK Android (composants Google) n'est pas inclus : scripts/install_android_sdk.sh l'installe
# dans le volume /workspace au premier démarrage, après acceptation explicite de ses licences.
ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/workspace/android-sdk \
    PE_ANDROID_SDK_ROOT=/workspace/android-sdk \
    PE_ANDROID_SYSTEM_IMAGE="system-images;android-30;google_apis;x86_64" \
    PE_DATA_DIR=/workspace/phone_emulator \
    PE_DEVICE_BACKEND=emulator \
    PE_WEB_DIST=/app/apps/web/dist \
    PE_ADB_PATH=/workspace/android-sdk/platform-tools/adb \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PATH=/workspace/android-sdk/platform-tools:/workspace/android-sdk/emulator:/workspace/android-sdk/cmdline-tools/latest/bin:$PATH

# Bibliothèques nécessaires à l'émulateur sans fenêtre ; aucun périphérique caméra/audio n'est mappé.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip openjdk-17-jre-headless openssh-server tini \
      libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libxdamage1 \
      libxrandr2 libxkbfile1 libasound2 libdbus-1-3 libfontconfig1 libx11-6 libxext6 \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md LICENSE NOTICE ./
COPY services/ services/
RUN uv sync --frozen --no-dev && uv run --no-sync python -c "import control.api, android_bridge.device"
COPY scripts/ scripts/
COPY --from=web /src/apps/web/dist apps/web/dist

EXPOSE 8000 22
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/scripts/pod_start.sh"]
