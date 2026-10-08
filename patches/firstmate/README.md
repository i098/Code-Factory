# Firstmate patches

Fixes for upstream [Firstmate](https://github.com/kunchenguid/firstmate) that upstream does not have yet. Each apply puts the Firstmate checkout on `origin/main` plus one local commit per file here, in file-name order (`scripts/firstmate-patch-layer.sh`, called from `ansible/tasks/firstmate.yml`).

To add a patch, commit the fix on top of upstream `main` in a Firstmate clone, run `git format-patch -1`, and save the file here as `<next number>-<short name>.patch`. Keep the `From:` line generic: the commit on each host takes its author, date, and message from the file.

[Firstmate patch layer](../../docs/dependencies.md#firstmate-patch-layer) tells what each patch does, how apply handles upstream changes, and how to drop a patch once upstream has it.
