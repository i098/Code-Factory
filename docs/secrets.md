# Shared credentials: super.env in Cloudflare Secrets Store

`~/super.env` on the primary VPS holds every shared fleet credential, with usage notes as comments. That VPS stays the one place the file is edited. Cloudflare Secrets Store keeps a copy, and a new agent host fetches it through a private Worker.

Never paste a value from this file into a repository, issue, PR, log, or chat. Compare copies by `sha256sum` only.

## What lives where

| Piece | Where | Notes |
| --- | --- | --- |
| Source of truth | `~/super.env` on the primary VPS, mode `600` | Edit here, then push. |
| One secret per variable | Account Secrets Store (`default_secrets_store`), named after the variable, comment `super.env`, scope `workers` | Holds the value without one surrounding pair of matching quotes. |
| Repeated variable names | `NAME` holds the last assignment, the one `source` keeps. Earlier ones are `NAME__1`, `NAME__2`, … in file order | Today only `SENTRY_ORG` repeats, so `SENTRY_ORG__1` exists. |
| Everything else: comments, blank lines, quotes, order | Secret `super_env_layout` | The comments hold retired credentials, so they are a secret too. |
| Fetch endpoint | Worker `fleet-secrets` on custom domain `fleet-secrets.iterative.sh` | No `workers.dev` or preview URL. Answers with `Cache-Control: no-store`. |
| Gate | Cloudflare Access app `fleet-secrets`, one policy: Service Auth for service token `fleet-secrets-fetch` | The Worker also verifies the Access JWT: issuer, audience, expiry, signature, and the token's client id. Anything else gets `403`. |
| Fetch credential | `FLEET_SECRETS_ACCESS_CLIENT_ID`, `FLEET_SECRETS_ACCESS_CLIENT_SECRET` at the end of `~/super.env` | Expires one year after creation. |

`workers/fleet-secrets/split.jq` defines the split. The Worker rebuilds the file byte for byte from `super_env_layout` plus the per-variable secrets.

Limits: a secret holds at most 65,536 bytes, and an account holds at most 100 secrets during the Secrets Store beta. Every current value and the layout fit in one secret, so nothing is chunked. The push script refuses an empty value, a value or layout above the limit, and a variable named `super_env_layout`. The file has 72 variables today, so the store holds 73 secrets.

## Push after editing super.env

On the VPS, from this repository:

```bash
scripts/push-super-env.sh
```

It reads `CLOUDFLARE_ACCOUNT_ID` and the account token `CF_API_TOKEN_GLOBAL` from the file itself. It creates or overwrites every secret, then redeploys the Worker with one binding per variable, then turns `workers.dev` and preview URLs off. Running it twice leaves the same state.

If a variable was deleted from the file, the script lists the orphaned secret names and deletes nothing. Delete them with:

```bash
scripts/push-super-env.sh --prune
```

Only secrets whose comment is `super.env` are ever pruned.

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

The script also accepts the two values as environment variables of the same names. It refuses a credentials file that is not mode `600`, and it never takes the values as arguments. On any HTTP status other than `200`, the existing `~/super.env` stays unchanged. `FLEET_SECRETS_URL`, `FLEET_SECRETS_CREDENTIALS`, and `SUPER_ENV` override the URL, the credentials file, and the output path.

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

## Variables

Values, emails, account ids, card numbers, and passwords are never listed here; read them from the file.

| Variable | Purpose |
| --- | --- |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account for Wrangler deploys and API calls |
| `CLOUDFLARE_API_TOKEN` | Cloudflare user API token for Wrangler: Workers, AI, D1, R2, KV, containers, and one zone |
| `CF_API_TOKEN_GLOBAL` | Cloudflare account-owned API token; `push-super-env.sh` uses it |
| `R2_ACCESS_KEY_ID` | R2 S3-compatible access key id |
| `R2_SECRET_ACCESS_KEY` | R2 S3-compatible secret key |
| `R2_S3_ENDPOINT` | R2 S3 endpoint URL |
| `CF_UNLABELED_KEY` | Cloudflare key of unstated purpose; ask before first use |
| `DORM_GH_APP_OWNER` | dorm GitHub App owner account |
| `DORM_GH_APP_ID` | dorm GitHub App id |
| `DORM_GH_APP_CLIENT_ID` | dorm GitHub App OAuth client id |
| `DORM_GH_APP_CLIENT_SECRET` | dorm GitHub App OAuth client secret |
| `DORM_GH_APP_KEY_FINGERPRINT` | Fingerprint of the dorm GitHub App private key |
| `DORM_GH_APP_PRIVATE_KEY` | dorm GitHub App private key, for minting installation tokens |
| `SUBLIMINAL_AWS_ACCESS_KEY_ID` | AWS IAM access key id, Subliminal client work only |
| `SUBLIMINAL_AWS_SECRET_ACCESS_KEY` | AWS IAM secret key, Subliminal client work only |
| `GOOGLE_ACCOUNT_EMAIL` | Google identity for registering service accounts |
| `GOOGLE_ACCOUNT_PASSWORD` | Its password; one automated sign-in attempt at most |
| `SUBLIMINAL_GOOGLE_ACCOUNT_EMAIL` | Subliminal Google Workspace account |
| `SUBLIMINAL_GOOGLE_ACCOUNT_PASSWORD_SOURCE` | Which stored password that account shares |
| `SENTRY_DSN` | Upscyled Tokens Sentry ingest DSN |
| `SENTRY_ORG__1` | Upscyled Tokens Sentry organization (first `SENTRY_ORG` in the file) |
| `SENTRY_PROJECT` | Upscyled Tokens Sentry project |
| `SLACK_BOT_TOKEN` | Incident-alert Slack bot token; can post, cannot read history |
| `SLACK_TEAM_ID` | Slack workspace id for that bot |
| `SLACK_ALERT_CHANNEL_SENTRY` | Slack channel id for Sentry alerts |
| `ALERT_WEBHOOK_SECRET` | Shared header secret Sentry presents to the alert translator |
| `ALERT_TRANSLATOR_URL` | Alert translator Worker URL |
| `POSTHOG_PROJECT_API_KEY` | Upscyled Tokens PostHog ingest key |
| `POSTHOG_HOST` | PostHog host |
| `POSTHOG_PROJECT_ID` | PostHog project id |
| `RHO_CARD_NUMBER` | Virtual payment card number |
| `RHO_CARD_EXP` | Card expiry |
| `RHO_CARD_HOLDER` | Cardholder name |
| `RHO_CARD_BILLING_ADDRESS` | Card billing street address |
| `RHO_CARD_BILLING_CITY` | Card billing city |
| `RHO_CARD_BILLING_STATE` | Card billing state |
| `RHO_CARD_BILLING_ZIP` | Card billing postal code |
| `RHO_CARD_BILLING_COUNTRY` | Card billing country |
| `SENTRY_AUTH_TOKEN` | Subliminal Sentry user auth token |
| `SENTRY_ORG_AUTH_TOKEN` | Subliminal Sentry organization auth token |
| `SENTRY_ORG` | Subliminal Sentry organization (the value `source` keeps) |
| `SENTRY_URL` | Subliminal Sentry URL |
| `OMNIROUTE_DASHBOARD` | OmniRoute AI gateway dashboard URL, local to the VPS |
| `OMNIROUTE_API` | OmniRoute API URL |
| `OMNIROUTE_API_KEY` | OmniRoute API key |
| `OMNIROUTE_PASSWORD` | OmniRoute dashboard password |
| `GITHUB_ACCOUNT_EMAIL` | GitHub web sign-in email; 2FA still needs the owner |
| `GITHUB_ACCOUNT_LOGIN` | GitHub account login |
| `GITHUB_2FA_EMAIL` | Address GitHub sends verification codes to |
| `GITHUB_ACCOUNT_PASSWORD` | GitHub web sign-in password |
| `ANTHROPIC_ACCOUNT_1_EMAIL` | First Claude subscription account, for account rotation |
| `ANTHROPIC_ACCOUNT_2_EMAIL` | Second Claude subscription account |
| `ANTHROPIC_ACCOUNT_PASSWORD` | Password shared by both Claude accounts |
| `SUBLIMINAL_PROD_AWS_ACCOUNT_ID` | Subliminal production AWS account; touch only what a task requires |
| `SUBLIMINAL_PROD_AWS_SIGNIN_URL` | Its console sign-in URL |
| `SUBLIMINAL_PROD_AWS_USERNAME` | Its IAM console user |
| `SUBLIMINAL_PROD_AWS_PASSWORD` | That user's console password |
| `SUBLIMINAL_PROD_AWS_ACCESS_KEY_ID` | That user's access key id |
| `SUBLIMINAL_PROD_AWS_SECRET_ACCESS_KEY` | That user's secret key |
| `SUBLIMINAL_PROD_AWS_PROFILE` | AWS CLI profile name holding that key |
| `SUBLIMINAL_PROD_AWS_REGION` | Its default region |
| `FELLA_ANALYSIS_AWS_PROFILE` | AWS CLI profile for the Fella analysis devbox |
| `FELLA_ANALYSIS_AWS_ROLE_ARN` | Role that profile assumes |
| `FELLA_ANALYSIS_AWS_EXTERNAL_ID` | External id for that role |
| `FELLA_ANALYSIS_AWS_REGION` | Devbox region |
| `FELLA_ANALYSIS_DEVBOX_INSTANCE_ID` | Devbox EC2 instance, reached through SSM |
| `STRIPE_LIVE_SECRET_KEY` | Stripe live secret key |
| `SUBLIMINAL_OPENAI_API_KEY` | OpenAI project key, Subliminal client work only |
| `STRIPE_LIVE_WEBHOOK_SECRET` | Stripe live webhook signing secret |
| `STRIPE_LIVE_PRICE_ID` | Stripe live price id |
| `FLEET_SECRETS_ACCESS_CLIENT_ID` | Access service token client id for `fetch-super-env.sh` |
| `FLEET_SECRETS_ACCESS_CLIENT_SECRET` | Access service token secret for `fetch-super-env.sh` |
