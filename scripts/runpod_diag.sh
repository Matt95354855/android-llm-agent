#!/usr/bin/env bash
# Diagnostic de faisabilité Runpod (jalons B02/B03/C08 du cahier des charges).
# Lit uniquement l'état du Pod ; n'installe rien de persistant.
# Écrit le rapport dans /diag/report.txt puis le sert en HTTP sur le port 8000.
set -u
OUT=/diag/report.txt
mkdir -p /diag
exec > >(tee "$OUT") 2>&1

section() { printf '\n===== %s =====\n' "$1"; }

section "Date / hôte"
date -u; uname -a; cat /etc/os-release 2>/dev/null | head -3

section "CPU"
nproc
grep -m1 'model name' /proc/cpuinfo
echo "flags virtualisation (vmx=Intel, svm=AMD) :"
grep -o -w -E 'vmx|svm|hypervisor' /proc/cpuinfo | sort | uniq -c

section "Mémoire / disque"
free -g; df -h / /workspace 2>/dev/null

section "KVM"
ls -l /dev/kvm 2>&1
if [ -e /dev/kvm ]; then
  python3 - <<'EOF'
import os, fcntl
try:
    fd = os.open("/dev/kvm", os.O_RDWR)
    ver = fcntl.ioctl(fd, 0xAE00)  # KVM_GET_API_VERSION
    print("KVM ouvrable, API version", ver)
except Exception as e:
    print("KVM présent mais inutilisable :", e)
EOF
fi
lsmod 2>/dev/null | grep -i kvm || echo "lsmod: aucun module kvm visible (normal en conteneur)"

section "Périphériques réseau / tun"
ls -l /dev/net/tun 2>&1
ip -br addr 2>/dev/null || cat /proc/net/dev

section "Capacités du conteneur"
grep -E 'Cap(Inh|Prm|Eff|Bnd)' /proc/self/status
command -v capsh >/dev/null && capsh --decode="$(grep CapEff /proc/self/status | awk '{print $2}')"
echo "seccomp: $(grep Seccomp /proc/self/status)"
echo "privilégié ? (accès /dev complet)"; ls /dev | head -50

section "Cgroups / runtime"
cat /proc/1/cgroup | head; cat /proc/self/mountinfo | grep -E ' / |cgroup' | head -5
[ -e /.dockerenv ] && echo "/.dockerenv présent"
grep -qi gvisor /proc/version 2>/dev/null && echo "gVisor détecté"
dmesg 2>&1 | head -3

section "binfmt (traduction ARM)"
ls /proc/sys/fs/binfmt_misc/ 2>&1

section "GPU"
nvidia-smi 2>&1 | head -15 || echo "pas de GPU"

section "IP de sortie publique (C08)"
for u in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
  printf '%s -> ' "$u"; curl -4 -s --max-time 8 "$u" || echo "échec"; echo
done
printf 'IPv6 -> '; curl -6 -s --max-time 8 https://api64.ipify.org || echo "pas d'IPv6"; echo

section "Variables Runpod (non sensibles)"
env | grep -E '^RUNPOD_(POD_ID|DC_ID|CPU_COUNT|MEM_GB|PUBLIC_IP|TCP_PORT|GPU_COUNT)' || true

section "FIN"
