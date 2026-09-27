#!/usr/bin/env bash
# Fetch super.env from the fleet-secrets Worker into ~/super.env (mode 600, atomic replace).
# Credentials: FLEET_SECRETS_ACCESS_CLIENT_ID and FLEET_SECRETS_ACCESS_CLIENT_SECRET as NAME=value
# lines in ~/.config/fleet-secrets.env (mode 600); never arguments or the environment.
# See docs/secrets.md.
set -euo pipefail
umask 077

url=${FLEET_SECRETS_URL:-https://fleet-secrets.iterative.sh/}
dest=$HOME/super.env
creds=$HOME/.config/fleet-secrets.env

if [[ $(stat -c %a "$creds" 2>/dev/null) != 600 ]]; then
  echo "Write FLEET_SECRETS_ACCESS_CLIENT_ID and _SECRET to $creds (mode 600)." >&2
  exit 1
fi
unset FLEET_SECRETS_ACCESS_CLIENT_ID FLEET_SECRETS_ACCESS_CLIENT_SECRET
while IFS='=' read -r key value || [[ -n $key ]]; do
  case $key in
  FLEET_SECRETS_ACCESS_CLIENT_ID | FLEET_SECRETS_ACCESS_CLIENT_SECRET) printf -v "$key" %s "$value" ;;
  esac
done <"$creds"

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
