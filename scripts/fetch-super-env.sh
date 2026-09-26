#!/usr/bin/env bash
# Fetch super.env from the fleet-secrets Worker into ~/super.env (mode 600, atomic replace).
# Credentials: FLEET_SECRETS_ACCESS_CLIENT_ID and FLEET_SECRETS_ACCESS_CLIENT_SECRET from the
# environment, else NAME=value lines in a mode-600 file (FLEET_SECRETS_CREDENTIALS, default
# ~/.config/fleet-secrets.env). Never pass them as arguments. See docs/secrets.md.
set -euo pipefail
umask 077

url=${FLEET_SECRETS_URL:-https://fleet-secrets.iterative.sh/}
dest=${SUPER_ENV:-$HOME/super.env}
creds=${FLEET_SECRETS_CREDENTIALS:-$HOME/.config/fleet-secrets.env}

if [[ -z ${FLEET_SECRETS_ACCESS_CLIENT_ID:-} || -z ${FLEET_SECRETS_ACCESS_CLIENT_SECRET:-} ]]; then
  if [[ $(stat -c %a "$creds" 2>/dev/null) != 600 ]]; then
    echo "Set FLEET_SECRETS_ACCESS_CLIENT_ID and _SECRET, or write them to $creds (mode 600)." >&2
    exit 1
  fi
  while IFS='=' read -r key value; do
    case $key in
    FLEET_SECRETS_ACCESS_CLIENT_ID | FLEET_SECRETS_ACCESS_CLIENT_SECRET) printf -v "$key" %s "$value" ;;
    esac
  done <"$creds"
fi

tmp=$(mktemp "$dest.XXXXXX")
headers=$(mktemp)
trap 'rm -f "$tmp" "$headers"' EXIT
printf 'CF-Access-Client-Id: %s\nCF-Access-Client-Secret: %s\n' \
  "${FLEET_SECRETS_ACCESS_CLIENT_ID:?}" "${FLEET_SECRETS_ACCESS_CLIENT_SECRET:?}" >"$headers"
status=$(curl -sS -H @"$headers" -o "$tmp" -w '%{http_code}' "$url")
if [[ $status != 200 || ! -s $tmp ]]; then
  echo "fetch failed: HTTP $status from $url; $dest left unchanged." >&2
  exit 1
fi
mv -f "$tmp" "$dest"
echo "wrote $dest ($(sha256sum <"$dest" | cut -d' ' -f1))"
