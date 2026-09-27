#!/usr/bin/env bash
# Sync ~/super.env into Cloudflare Secrets Store and redeploy the fleet-secrets Worker.
# Usage: scripts/push-super-env.sh      See docs/secrets.md.
# Uses CLOUDFLARE_ACCOUNT_ID and CF_API_TOKEN_GLOBAL from the file itself. Secret values only
# travel through mode-600 temp files, never argv, and nothing prints them.
set -euo pipefail
umask 077

src=$HOME/super.env
worker=fleet-secrets
host=fleet-secrets.iterative.sh
dir=$(cd "$(dirname "$0")/../workers/$worker" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

jq -Rs -f "$dir/split.jq" "$src" >"$tmp/split.json"
jq '[(.secrets | to_entries[] | {name: .key, value}),
     {name: "super_env_layout", value: (.layout | tojson)}]
    | map(. + {scopes: ["workers"], comment: "super.env"})' "$tmp/split.json" >"$tmp/entries.json"
account=$(jq -er .secrets.CLOUDFLARE_ACCOUNT_ID "$tmp/split.json")
jq -j '"Authorization: Bearer \(.secrets.CF_API_TOKEN_GLOBAL // error("no CF_API_TOKEN_GLOBAL"))\n"' \
  "$tmp/split.json" >"$tmp/auth"

api() { # METHOD PATH [curl args...]; prints the response, fails on success=false
  local method=$1 path=$2 out
  shift 2
  out=$(curl -sS -X "$method" -H @"$tmp/auth" "$@" \
    "https://api.cloudflare.com/client/v4/accounts/$account$path")
  jq -e .success <<<"$out" >/dev/null || {
    jq -c .errors <<<"$out" >&2
    return 1
  }
  printf '%s\n' "$out"
}
send() { api "$1" "$2" -H 'Content-Type: application/json' --data-binary @"$3" >/dev/null; }

# The Worker checks the Access JWT against these, so they are looked up, never hand-set.
team=$(api GET /access/organizations | jq -er .result.auth_domain)
aud=$(api GET /access/apps | jq -er --arg h "$host" '[.result[] | select(.domain == $h)] | .[0].aud')
store=$(api GET /secrets_store/stores | jq -er '.result[0].id')
secrets=/secrets_store/stores/$store/secrets
# ponytail: one page; the store holds at most 100 secrets per account during the beta.
api GET "$secrets?per_page=100" | jq '[.result[] | {(.name): {id, comment}}] | add // {}' \
  >"$tmp/existing.json"

jq -r --slurpfile have "$tmp/existing.json" \
  'map(select($have[0][.name] and $have[0][.name].comment != "super.env") | .name)
   | if length > 0 then error("not created by this script, refusing to overwrite: \(join(" "))")
     else empty end' "$tmp/entries.json"
jq --slurpfile have "$tmp/existing.json" 'map(select($have[0][.name] == null))' \
  "$tmp/entries.json" >"$tmp/create.json"
[[ $(jq length "$tmp/create.json") == 0 ]] || send POST "$secrets" "$tmp/create.json"
jq -r --slurpfile have "$tmp/existing.json" \
  '.[] | select($have[0][.name]) | "\($have[0][.name].id) \(.name)"' "$tmp/entries.json" |
  while read -r id name; do
    jq --arg n "$name" '.[] | select(.name == $n) | del(.name)' "$tmp/entries.json" >"$tmp/body"
    send PATCH "$secrets/$id" "$tmp/body"
  done

jq --arg store "$store" --arg team "$team" --arg aud "$aud" '{
    main_module: "index.js",
    compatibility_date: "2026-09-01",
    observability: {enabled: false},
    logpush: false,
    bindings: (map({type: "secrets_store_secret", name, store_id: $store, secret_name: .name})
      + [{type: "plain_text", name: "team_domain", text: $team},
         {type: "plain_text", name: "aud", text: $aud}])
  }' "$tmp/entries.json" >"$tmp/metadata.json"
api PUT "/workers/scripts/$worker" \
  -F "metadata=@$tmp/metadata.json;type=application/json" \
  -F "index.js=@$dir/index.js;type=application/javascript+module" >/dev/null
echo '{"enabled": false, "previews_enabled": false}' >"$tmp/subdomain.json"
send POST "/workers/scripts/$worker/subdomain" "$tmp/subdomain.json"
echo "Pushed $(jq length "$tmp/entries.json") secrets from $src; Worker $worker deployed."

jq -r --slurpfile want "$tmp/entries.json" \
  '($want[0] | map({(.name): true}) | add) as $w
   | to_entries[] | select(.value.comment == "super.env" and ($w[.key] | not)) | .key' \
  "$tmp/existing.json" >"$tmp/stale"
[[ -s $tmp/stale ]] || exit 0
echo "Secrets whose variable is no longer in $src; delete them by hand in the dashboard:"
cat "$tmp/stale"
