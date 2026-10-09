# harbor

`harbor/` is the website for [crewship.si](https://crewship.si): a first-person walk around the ship at the dock, drawn as text in the browser every frame. Each object on the ship opens a short card for one Crewship feature. The page lists the same features and links in plain HTML for screen readers and for visitors without JavaScript.

It is plain HTML, CSS and JavaScript in `public/`, with no build step and no dependencies. Nothing here is part of a host or an image: `.dockerignore` excludes `harbor/`, the playbook never copies it, and `tests/test_harbor_isolation.py` checks both.

## Preview

```bash
python3 -m http.server --directory harbor/public 8000
```

Then open <http://localhost:8000>.

## Deploy

Cloudflare Workers serves `public/` as static assets; `wrangler.jsonc` is the configuration. The [harbor workflow](../.github/workflows/harbor.yml) deploys on every push to `main` that changes `harbor/`, and on a manual run. Each run is a GitHub deployment in the `crewship.si` environment, which holds the deploy token as its `CLOUDFLARE_API_TOKEN` secret and the account id as its `CLOUDFLARE_ACCOUNT_ID` variable, and accepts only `main`.

To deploy by hand with a token that can edit the `crewship` Worker:

```bash
cd harbor
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... npx wrangler@latest deploy
```

The site serves on the Worker's `workers.dev` address. When the `crewship.si` zone is active, add `"routes": [{ "pattern": "crewship.si", "custom_domain": true }]` to `wrangler.jsonc`; the deploy token then also needs Workers Routes edit on that zone.
