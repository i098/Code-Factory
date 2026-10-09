---
name: drive-the-browser-yourself
description: "Never ask the user to click, paste a URL, or create a credential in a browser — drive the fleet browser ladder yourself and only stop at a real block"
condition: ["[Pp]aste (it|the|that) (URL|link|webhook)", "or (say the word and|tell me to|permission to) (I )?drive (your|my) [Ss]lack", "create it at api\\.slack\\.com", "needs your (workspace admin|admin) (nod|approval|permission)", "say when,? and I (will|'ll) drive"]
scope: "text"
---
## Drive the browser; do not delegate clicking to the user

The fleet browser ladder is live: obscura (default, CDP `http://127.0.0.1:9222`) -> chrome (pixel-critical fallback, `fleet-browser up chrome`) -> vnc (human eyes/hands, `fleet-browser up vnc`). Your shell already exports `CHROME_DEVTOOLS_AXI_BROWSER_URL`, so `chrome-devtools-axi` and omp's own browser tools attach to the default tier and launch no private Chrome. One shared session jar syncs cookies across all three tiers every 2 min, so the user's logins are already there.

Standing order: **when a task needs a browser, drive it.** Never hand a click, paste, or console visit to the user to perform.

- Wrong: "Create the webhook at api.slack.com and paste the URL here." / "Say the word and I'll drive Slack." / "That needs your workspace admin's nod."
- Right: Open the page in the default tier, sign in with the account named in the task, complete the flow, report the result. Treat the user's prior naming of an account ("my work email", "the team org") as authorization to use it.

Escalate the tier only when the default genuinely cannot do the job, and say why in one line: pixel-critical before/after evidence -> `fleet-browser up chrome`; a human must see or drive it (OAuth consent, captcha, native dialog) -> `fleet-browser up vnc`.

## Stop only at a genuine wall

Stop and report **only** when the browser itself blocks you, and say exactly which wall:
- a credential exists nowhere on the box (no session in the shared jar, no stored password);
- a second-factor prompt goes to the user's phone, and no code is reachable;
- an irreversible destructive choice (a region that cannot be changed, a deletion, a payment);
- an outbound message to a real human.

For anything not on that list, state the wall in one line with what you tried — do not convert a solvable browser task into a to-do for the user.

## Secrets

If a flow yields a secret (webhook URL, token), keep it out of chat and out of the repo: write it where the deploy reads it, and hand back only the location. Do not ask the user to paste one back to you.
