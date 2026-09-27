# Shared credentials: super.env in Cloudflare Secrets Store

`~/super.env` on the primary VPS holds every shared fleet credential. That VPS stays the one place the file is edited. Cloudflare Secrets Store keeps a copy, and a new agent host fetches it through a private Worker. The fetched file carries its own usage notes as comments.

Never paste a value from this file into a repository, issue, PR, log, or chat. Compare copies by `sha256sum` only.

## What lives where

| Piece | Where | Notes |
| --- | --- | --- |
| Source of truth | `~/super.env` on the primary VPS, mode `600` | Edit here, then push. |
| One secret per variable | Account Secrets Store (`default_secrets_store`), named after the variable, comment `super.env`, scope `workers` | Holds the value without one surrounding pair of matching quotes. |
| Repeated variable names | Secrets `NAME`, `NAME__1`, `NAME__2`, … | `NAME` holds the last assignment, the one `source` keeps. Earlier ones are numbered in file order. |
| Everything else: comments, blank lines, quotes, order | Secret `super_env_layout` | The comments hold retired credentials, so they are a secret too. |
| Fetch endpoint | Worker `fleet-secrets` on custom domain `fleet-secrets.iterative.sh` | No `workers.dev` or preview URL. Answers with `Cache-Control: no-store`. |
| Gate | Cloudflare Access app `fleet-secrets`, one policy: Service Auth for service token `fleet-secrets-fetch` | The Worker also verifies the Access JWT: issuer, audience, expiry, signature, and the token's client id. Anything else gets `403`. |
| Fetch credential | `FLEET_SECRETS_ACCESS_CLIENT_ID`, `FLEET_SECRETS_ACCESS_CLIENT_SECRET` at the end of `~/super.env` | Expires one year after creation. |

`workers/fleet-secrets/split.jq` defines the split. The Worker rebuilds the file byte for byte from `super_env_layout` plus the per-variable secrets.

Limits: a secret holds at most 65,536 bytes, and an account holds at most 100 secrets during the Secrets Store beta. Every current value and the layout fit in one secret, so nothing is chunked. The push script refuses an empty value, a value or layout above the limit, and a variable whose secret name would collide with another binding: `super_env_layout`, `team_domain`, `aud`, or a generated `NAME__n`.

## Push after editing super.env

On the VPS, from this repository:

```bash
scripts/push-super-env.sh
```

It reads `CLOUDFLARE_ACCOUNT_ID` and the account token `CF_API_TOKEN_GLOBAL` from the file itself. It creates or overwrites every secret, then redeploys the Worker with one binding per variable, then turns `workers.dev` and preview URLs off. It refuses to overwrite a same-named secret whose comment is not `super.env`. Running it twice leaves the same state.

If a variable was deleted from the file, the script lists the orphaned secret names and deletes nothing. Delete them by hand in the Cloudflare dashboard's Secrets Store.

## Fetch on a new host

1. On the VPS, copy the two lines `FLEET_SECRETS_ACCESS_CLIENT_ID=…` and `FLEET_SECRETS_ACCESS_CLIENT_SECRET=…` from `~/super.env`. Copy them by hand, over SSH or a password manager; never through chat, a ticket, or a repository.
2. On the new host, write them to `~/.config/fleet-secrets.env` and restrict it:

   ```bash
   mkdir -p ~/.config && chmod 700 ~/.config
   install -m 600 /dev/null ~/.config/fleet-secrets.env
   "${EDITOR:-nano}" ~/.config/fleet-secrets.env
   ```

3. From a checkout of this repository, run:

   ```bash
   scripts/fetch-super-env.sh
   ```

   It writes `~/super.env` at mode `600` through a temp file and an atomic rename, then prints its sha256. It must equal `sha256sum ~/super.env` on the VPS.

The script reads the two values only from `~/.config/fleet-secrets.env`. It refuses that file unless it is mode `600`, and it never takes the values as arguments or environment variables. On any HTTP status other than `200`, the existing `~/super.env` stays unchanged. `FLEET_SECRETS_URL` overrides the URL.

A fetched copy is read-only in practice: edits made on it are overwritten by the next fetch. Make edits on the VPS and push.

## Revoke if a host is lost

1. Cloudflare dashboard → Zero Trust → Access → Service credentials → Service Tokens → `fleet-secrets-fetch` → Delete. Fetching stops immediately for every host.
2. Create a new service token, and replace the `token_id` in the `fleet-secrets` app's only policy.
3. Replace the two `FLEET_SECRETS_ACCESS_*` lines in `~/super.env` on the VPS with the new token's client id and secret, then run `scripts/push-super-env.sh`. The Worker only accepts the client id stored in `FLEET_SECRETS_ACCESS_CLIENT_ID`.
4. Copy the new lines to the remaining hosts.

Revoking the fetch token does not revoke what the lost host already fetched. It holds every credential in the file, so treat each one as exposed, and tell the owner.

Renew the token the same way before it expires; the Access dashboard shows the expiry date.

## One-time setup, for rebuilding

These already exist. Recreate them only if they are lost:

1. Access app `fleet-secrets`: self-hosted, domain `fleet-secrets.iterative.sh`, session 15 minutes, hidden from the App Launcher, no identity providers. Its only policy: decision Service Auth, include only service token `fleet-secrets-fetch`.
2. Run `scripts/push-super-env.sh`. It reads the team domain and the app's Application Audience tag from the Access API on every push and binds them to the Worker.
3. Add the Worker custom domain `fleet-secrets.iterative.sh` only after the Access app exists.
