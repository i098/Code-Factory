# Private rules

omp rules that stay on this host. Git ignores everything in this folder except this file, so nothing here is committed or shared. Put each rule in `rules/private/<name>.md`, or set `skills.private_source` to fill this folder from the `rules/` folder of a private source on every apply. The `agents` profile installs them like [public rules](../public/README.md), and a private rule wins over a public rule with the same name. See [Rules](../../docs/omp.md#rules).
