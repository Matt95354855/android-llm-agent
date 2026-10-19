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
ARG CMDLINE_TOOLS_VERSION=11076708
ARG SYSTEM_IMAGE="system-images;android-30;google_apis;x86_64"
ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    PE_ANDROID_SDK_ROOT=/opt/android-sdk \
    PE_ANDROID_SYSTEM_IMAGE=${SYSTEM_IMAGE} \
    PE_DATA_DIR=/workspace/phone_emulator \
    PE_DEVICE_BACKEND=emulator \
    PE_WEB_DIST=/app/apps/web/dist \
    PE_ADB_PATH=/opt/android-sdk/platform-tools/adb \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PATH=/opt/android-sdk/platform-tools:/opt/android-sdk/emulator:/opt/android-sdk/cmdline-tools/latest/bin:/root/.local/bin:$PATH

# Bibliothèques nécessaires à l'émulateur sans fenêtre ; aucun périphérique caméra/audio n'est mappé.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip openjdk-17-jre-headless openssh-server tini \
      libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libxdamage1 \
      libxrandr2 libxkbfile1 libasound2 libdbus-1-3 libfontconfig1 libx11-6 libxext6 \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd

RUN mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools && cd /tmp \
    && curl -fsSLo tools.zip https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip \
    && unzip -q tools.zip -d ${ANDROID_SDK_ROOT}/cmdline-tools && mv ${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest \
    && rm tools.zip \
    && yes | sdkmanager --licenses >/dev/null \
    && sdkmanager --install "platform-tools" "emulator" "${SYSTEM_IMAGE}" >/dev/null \
    && sdkmanager --list_installed > ${ANDROID_SDK_ROOT}/INSTALLED.txt

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
COPY services/ services/
RUN uv sync --frozen --no-dev
COPY scripts/ scripts/
COPY --from=web /src/apps/web/dist apps/web/dist

EXPOSE 8000 22
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/scripts/pod_start.sh"]
