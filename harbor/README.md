# harbor

`harbor/` is the website for [crewship.si](https://crewship.si): a full-screen, first-person walk around the ship at the dock, drawn as text in the browser every frame. Each object opens a floating label for one Crewship feature, an ASCII mini map jumps to any of them, and [how.html](public/how.html) explains how it is built. The page also lists every feature and link in plain HTML for screen readers and for visitors without JavaScript.
An uncaught error hides the scene and shows the plain page.

The island has staggered plaza paving, scattered stones and grass tufts, varied tree canopies, textured bark, and foam along the shore.

Walk into the framed house door to enter a warm room with a lamp, table, bed, and a starry night window.
The blue bed faces the door; darker walls and floor keep the furniture, lamp, and window clear.
Walk back through the inside door to return just outside, facing the island.
Keyboard and touch movement share the door transition; walls and furniture block walking, and the map stays hidden inside.
Release the movement keys and touch pad after a door crossing to move again.
The renderer adjusts detail from rendering cost and missed room frames, relative to the measured display refresh rate.

The plaza fountain has an octagonal stone rim, a central spout, and water that uses the existing animation clock.
Its basin blocks walking, and a blue `O` marks it on the mini map.
The fountain marker leaves map labels and selected point markers clear.
Map walks check complete approach segments against the plaza walking collision bounds and route around the basin and all four hedges.
If a road route or either approach has no clear path, the map walk stops without moving the player.
Detour completeness remains in [#150](https://github.com/i098/Crewship/issues/150).

It is plain HTML, CSS and JavaScript in `public/`, with no dependencies. Nothing here is part of a host or an image: `.dockerignore` excludes `harbor/`, the playbook never copies it, and `tests/test_harbor_isolation.py` checks both.

## Content from the repository

`build.py` (Python standard library) copies `public/` to `dist/` and fills the points of interest from the README's Features list and More docs row.
It also adds the quick start, the repository, the latest release with the next changes from `CHANGELOG.md`, and how.html.
A link with an object in the scene (mapped in `build.py`'s `SCENE`) opens on that object.
A link with no mapping never blocks the build: it prints a warning and appears on the docs board beside the HOW board.
The docs board shows on the mini map like the other points.
Add an object and a `SCENE` entry to give the link its own place.

## Preview

```bash
python3 harbor/build.py
python3 -m http.server --directory harbor/dist 8000
```

Then open <http://localhost:8000>.

## WebKit check

CI loads the built page in Playwright WebKit as an iPhone, with `webkit-check.mjs`.
The check also fails if the first 30 slow exterior frames change the grid, cell size, field of view, or canvas layout.
The check walks through the house door and back with the touch pad.
It fails on a crash, an uncaught error, a console error, a fallback to the plain page, or a multi-glyph `fillText` call.
See [how.html](public/how.html) for the rendering limits on touch devices.
To run the check locally:

```bash
python3 harbor/build.py
cd harbor
npm install --no-save --no-package-lock --prefix . playwright
npx playwright install --with-deps webkit
node webkit-check.mjs
```

## Deploy

Cloudflare Workers serves `dist/` as static assets; `wrangler.jsonc` is the configuration. The [harbor workflow](../.github/workflows/harbor.yml) builds and deploys on every push to `main`, on each published release, and on a manual run. Each run is a GitHub deployment in the `crewship.si` environment, which accepts only `main` and `v*` tags and holds the deploy token as its `CLOUDFLARE_API_TOKEN` secret and the account id as its `CLOUDFLARE_ACCOUNT_ID` variable.

To deploy by hand with a token that can edit the `crewship` Worker:

```bash
python3 harbor/build.py
cd harbor
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... npx wrangler@latest deploy
```

The site serves on https://crewship.si, a custom domain attached to the Worker outside `wrangler.jsonc`, and each deploy records that URL under Deployments.
