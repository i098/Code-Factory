---
name: opus-speed
description: Use when running as Opus 5. Wall-clock speed rules: parallelize, delegate by complexity to subagents, no idle waiting, no overlapping subagent scope.
---

## Speed (Opus 5 only)

When running as Opus 5, optimize for wall-clock speed. Finish tasks quickly.

- Parallelize aggressively. Independent tasks run at the same time, never one after another - batch tool calls, spawn subagents concurrently.
- Delegate by complexity: Sonnet 5 subagents for routine work (search, bulk edits, boilerplate, verification), Opus 5 subagents for hard reasoning that can run independently.
- Keep working in the main thread while subagents run - do not sit idle waiting on them.
- Do not over-deliberate. Enough info to act = act. No long option surveys when the default decision is obvious.
- Speed never trades away quality: same rigor, same verification, same "done means done". If parallelizing risks a worse result, slow down.
- No conflicts from parallelism: never let two subagents touch the same files or overlapping scope. Split work by non-overlapping boundaries; merge and reconcile results in the main thread.
