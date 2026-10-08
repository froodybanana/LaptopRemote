#!/bin/bash
# Writes WireGuard config files for a hub-and-spoke network: a hub that both the laptop and every
# client can reach, the laptop, and one or more clients (the PC, a second PC). Nothing is installed;
# the commands to run on each machine are printed at the end.
#   bash remote/wireguard.sh --endpoint vpn.example.net:51820 --subnet 10.0.0.0/24 --out ./wg laptop pc
# Address plan: hub .1, laptop .2, clients .3 upwards in the order given. Needs `wg` (wireguard-tools;
# on Windows it ships with the WireGuard app).
set -euo pipefail

endpoint="" subnet="" out="./wireguard"
while [ $# -gt 0 ]; do
    case "$1" in
        --endpoint) endpoint=$2; shift 2 ;;
        --subnet) subnet=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --help|-h) sed -n '2,8p' "$0"; exit 0 ;;
        -*) echo "unknown option $1" >&2; exit 2 ;;
        *) break ;;
    esac
done
[ -n "$endpoint" ] && [ -n "$subnet" ] && [ $# -ge 2 ] || { echo "usage: wireguard.sh --endpoint HOST:PORT --subnet A.B.C.0/24 [--out DIR] laptop CLIENT..." >&2; exit 2; }
[ "$1" = laptop ] || { echo "the first peer name must be 'laptop'" >&2; exit 2; }
command -v wg >/dev/null || { echo "wg not found: install wireguard-tools (Windows: the WireGuard app's folder)" >&2; exit 1; }
printf '%s' "$subnet" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.0/24$' || { echo "subnet must be a /24 ending in .0, such as 10.0.0.0/24" >&2; exit 2; }
printf '%s' "$endpoint" | grep -Eq '^[A-Za-z0-9._-]+:[0-9]+$' || { echo "endpoint must be HOST:PORT, such as vpn.example.net:51820" >&2; exit 2; }
for name in "$@"; do printf '%s' "$name" | grep -Eq '^[A-Za-z0-9_-]+$' || { echo "peer name $name: letters, digits, - and _ only" >&2; exit 2; }; done

prefix=${subnet%.0/24}
port=${endpoint##*:}
mkdir -p "$out"
umask 077

hub_private=$(wg genkey); hub_public=$(printf '%s' "$hub_private" | wg pubkey)
{
    printf '[Interface]\nPrivateKey = %s\nAddress = %s.1/24\nListenPort = %s\n' "$hub_private" "$prefix" "$port"
} > "$out/hub.conf"

n=2
for name in "$@"; do
    private=$(wg genkey); public=$(printf '%s' "$private" | wg pubkey)
    {
        printf '[Interface]\nPrivateKey = %s\nAddress = %s.%s/24\n\n' "$private" "$prefix" "$n"
        printf '[Peer]\n# hub\nPublicKey = %s\nEndpoint = %s\nAllowedIPs = %s\nPersistentKeepalive = 25\n' "$hub_public" "$endpoint" "$subnet"
    } > "$out/$name.conf"
    printf '\n[Peer]\n# %s\nPublicKey = %s\nAllowedIPs = %s.%s/32\n' "$name" "$public" "$prefix" "$n" >> "$out/hub.conf"
    n=$((n + 1))
done

cat <<EOF
Wrote $out/hub.conf, $out/laptop.conf and one .conf per client (mode 600; each holds a private key).

Hub (Linux, as root):
  install -m 600 $out/hub.conf /etc/wireguard/wg0.conf
  sysctl -w net.ipv4.ip_forward=1 && echo net.ipv4.ip_forward=1 > /etc/sysctl.d/99-wireguard.conf
  systemctl enable --now wg-quick@wg0
  ufw allow $port/udp && ufw route allow in on wg0 out on wg0      # if ufw is in use

Laptop (as root):
  install -m 600 $out/laptop.conf /etc/wireguard/wg0.conf
  systemctl enable --now wg-quick@wg0
  ufw allow proto tcp from $subnet to any port 22,47800           # if ufw is in use

Windows clients: WireGuard app, "Import tunnel(s) from file", pick the client's .conf, Activate.

Then: the laptop's tunnel address is $prefix.2; pair from the viewer with that address so the agent
allows the tunnel, or add "$subnet" to allowed_addresses in ~/.config/laptopremote/config.toml.
EOF
