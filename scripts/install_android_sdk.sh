#!/usr/bin/env bash
# Installe le SDK Android dans le volume persistant au premier démarrage du Pod (idempotent).
# Les composants Google ne sont pas redistribués dans l'image publique : leurs licences doivent
# être acceptées explicitement par l'exploitant avec PE_ACCEPT_ANDROID_SDK_LICENSES=1.
set -euo pipefail

SDK="${PE_ANDROID_SDK_ROOT:-/workspace/android-sdk}"
IMAGE="${PE_ANDROID_SYSTEM_IMAGE:-system-images;android-30;google_apis;x86_64}"
CMDLINE_TOOLS_VERSION="${PE_CMDLINE_TOOLS_VERSION:-11076708}"
MARKER="$SDK/.pe_installed"

if [[ -f "$MARKER" ]] && grep -qxF "$IMAGE" "$MARKER"; then
  echo "[sdk] déjà installé dans $SDK"
  exit 0
fi
if [[ "${PE_ACCEPT_ANDROID_SDK_LICENSES:-0}" != "1" ]]; then
  echo "[sdk] SDK absent. Définissez PE_ACCEPT_ANDROID_SDK_LICENSES=1 pour accepter les licences" >&2
  echo "[sdk] du SDK Android (https://developer.android.com/studio/terms) et lancer l'installation." >&2
  exit 3
fi

mkdir -p "$SDK/cmdline-tools"
if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  tmp=$(mktemp -d)
  curl -fsSLo "$tmp/tools.zip" "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip"
  unzip -q "$tmp/tools.zip" -d "$tmp"
  rm -rf "$SDK/cmdline-tools/latest" && mv "$tmp/cmdline-tools" "$SDK/cmdline-tools/latest"
  rm -rf "$tmp"
fi
export ANDROID_SDK_ROOT="$SDK"
yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null || true  # SIGPIPE de yes attendu
"$SDK/cmdline-tools/latest/bin/sdkmanager" --install "platform-tools" "emulator" "$IMAGE"
"$SDK/cmdline-tools/latest/bin/sdkmanager" --list_installed > "$SDK/INSTALLED.txt"
echo "$IMAGE" > "$MARKER"
echo "[sdk] installé : $(grep -cE '^\s+[a-z]' "$SDK/INSTALLED.txt") composants (détail dans $SDK/INSTALLED.txt)"
