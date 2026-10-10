# harbor

`harbor/` is the website for [crewship.si](https://crewship.si): a full-screen, first-person walk around the ship at the dock, drawn as text in the browser every frame. Each object opens a floating label for one Crewship feature, an ASCII mini map jumps to any of them, and [how.html](public/how.html) explains how it is built. The page also lists every feature and link in plain HTML for screen readers and for visitors without JavaScript.

The island has staggered plaza paving, scattered stones and grass tufts, varied tree canopies, textured bark, and foam along the shore.

It is plain HTML, CSS and JavaScript in `public/`, with no dependencies. Nothing here is part of a host or an image: `.dockerignore` excludes `harbor/`, the playbook never copies it, and `tests/test_harbor_isolation.py` checks both.

## Content from the repository

`build.py` (Python standard library) copies `public/` to `dist/` and fills the points of interest: one per row of the README's Docs table, plus the quick start, the repository, the latest release with the next changes from `CHANGELOG.md`, and how.html. A Docs row with an object in the scene (mapped in `build.py`'s `SCENE`) opens on that object. A row with no mapping never blocks the build: it prints a warning and is listed, with its link, on the docs board beside the HOW board on the quay, which shows on the mini map like the other points. Add an object and a `SCENE` entry to give the row its own place.

## Preview

```bash
python3 harbor/build.py
python3 -m http.server --directory harbor/dist 8000
```

Then open <http://localhost:8000>.

Upload a branch preview without changing the production version:

```bash
python3 harbor/build.py
cd harbor
npx wrangler@latest versions upload --preview-alias <branch-alias>
```

Use a branch alias with letters, numbers and hyphens.
Set `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` for the upload.

## Deploy

Cloudflare Workers serves `dist/` as static assets; `wrangler.jsonc` is the configuration. The [harbor workflow](../.github/workflows/harbor.yml) builds and deploys on every push to `main`, on each published release, and on a manual run. Each run is a GitHub deployment in the `crewship.si` environment, which accepts only `main` and `v*` tags and holds the deploy token as its `CLOUDFLARE_API_TOKEN` secret and the account id as its `CLOUDFLARE_ACCOUNT_ID` variable.

To deploy by hand with a token that can edit the `crewship` Worker:

```bash
python3 harbor/build.py
cd harbor
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... npx wrangler@latest deploy
```

The site serves on https://crewship.si, a custom domain attached to the Worker outside `wrangler.jsonc`, and each deploy records that URL under Deployments.
