# Public rules

omp rules that ship with Crewship. Put each rule in `rules/public/<name>.md`, in omp's rule format: YAML frontmatter (`description`, and `alwaysApply`, or a TTSR `condition` and `scope`) and a Markdown body. The `agents` profile installs every rule here to omp's global rules folder (`~/.omp/agent/rules/`). A rule in [`rules/private/`](../private/README.md) with the same name wins on that host. Keep every rule here general: no paths, host names, user names, emails, accounts, or project names. See [Rules](../../docs/omp.md#rules).
