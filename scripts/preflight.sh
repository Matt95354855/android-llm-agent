#!/usr/bin/env bash
# Contrôle préalable avant activation des missions (W10, X02). Code de sortie non nul si un prérequis manque.
set -u
fail=0
ok()   { printf '  [ok]   %s\n' "$1"; }
ko()   { printf '  [MANQUE] %s\n' "$1"; fail=1; }
info() { printf '  [info] %s\n' "$1"; }

echo "Prérequis Android"
if [[ -r /dev/kvm && -w /dev/kvm ]]; then ok "/dev/kvm accessible"; else ko "/dev/kvm absent ou inaccessible : l'émulateur sera inutilisable ou très lent"; fi
if command -v emulator >/dev/null; then
  info "$(emulator -accel-check 2>&1 | tr '\n' ' ' | cut -c1-200)"
else
  ko "binaire emulator introuvable"
fi
command -v adb >/dev/null && ok "adb $(adb version | head -1 | awk '{print $5}')" || ko "adb introuvable"

echo "Stockage"
if [[ -d /workspace ]] && touch /workspace/.pe_write_test 2>/dev/null; then
  rm -f /workspace/.pe_write_test; ok "volume /workspace inscriptible ($(df -h /workspace | awk 'NR==2{print $4}') libres)"
else
  ko "volume /workspace absent : profils Android et base seraient perdus à l'arrêt"
fi

echo "Configuration"
[[ -n "${PE_ACCESS_TOKEN:-}" ]] && ok "jeton d'accès défini" || ko "PE_ACCESS_TOKEN non défini"
if [[ -n "${PE_LLM_BASE_URL:-}" ]] && curl -fsS --max-time 5 -H "Authorization: Bearer ${PE_LLM_API_KEY:-}" "$PE_LLM_BASE_URL/models" >/dev/null 2>&1; then
  ok "service modèle joignable ($PE_LLM_BASE_URL)"
else
  info "service modèle non joignable pour l'instant (${PE_LLM_BASE_URL:-non configuré})"
fi

echo "Réseau"
info "IP de sortie du Pod : $(curl -4 -s --max-time 8 https://api.ipify.org || echo 'inconnue')"

exit $fail
