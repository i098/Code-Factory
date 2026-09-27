# Split a dotenv file (read with jq -Rs) into one secret per assignment plus a layout
# that rebuilds the file byte for byte: [[text, secret_name], ..., [tail_text, null]].
# One surrounding pair of matching quotes is kept in the layout, not in the secret.
# A repeated NAME keeps NAME for its last assignment (the one `source` keeps);
# earlier assignments become NAME__1, NAME__2, ... in file order.
def limit: 65536;

split("\n")
| (.[:-1] | map(. + "\n")) + .[-1:]
| map(. as $line
    | ($line | rtrimstr("\n") | capture("^(?<name>[A-Za-z_][A-Za-z0-9_]*)=(?<value>.*)$") // {})
    + {line: $line})
| (map(.name // empty) | reduce .[] as $n ({}; .[$n] += 1)) as $total
| reduce .[] as $e ({layout: [], text: "", seen: {}, secrets: {}};
    if $e.name == null then .text += $e.line
    else
      ($e.value
       | if length > 1 and (.[:1] == "\"" or .[:1] == "'") and .[-1:] == .[:1]
         then .[:1] else "" end) as $q
      | .seen[$e.name] += 1
      | (if .seen[$e.name] == $total[$e.name] then $e.name
         else "\($e.name)__\(.seen[$e.name])" end) as $s
      | if .secrets[$s] != null or ($s | IN("super_env_layout", "team_domain", "aud"))
        then error("secret name collision: \($s)") else . end
      | .secrets[$s] = ($e.value | .[($q | length):(length - ($q | length))])
      | if (.secrets[$s] | utf8bytelength) > limit or (.secrets[$s] | length) == 0
        then error("\($s): Secrets Store needs 1..\(limit) bytes") else . end
      | .layout += [[.text + $e.name + "=" + $q, $s]]
      | .text = $q + ($e.line | if endswith("\n") then "\n" else "" end)
    end)
| {secrets, layout: (.layout + [[.text, null]])}
| if (.layout | tojson | utf8bytelength) > limit then error("layout exceeds \(limit) bytes") else . end
