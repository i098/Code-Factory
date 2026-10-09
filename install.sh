#!/usr/bin/env bash
# One command from a fresh Ubuntu 24.04 or 26.04 machine to a Crewship host:
#   curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
# Arguments go to `./ship.sh dock` (for example `bash -s -- --container`).
# Installs the OS prerequisites, clones the latest release into ~/Crewship,
# then runs onboard, dock, inspect, chart and launch. Safe to run again: each
# step skips or reports no change when its work is already done.
set -euo pipefail

main() {
  local repo=${CREWSHIP_REPO:-https://github.com/i098/Crewship.git}
  local dir=$HOME/Crewship
  local ref=${CREWSHIP_REF:-}
  local sudo=sudo
  [ "$(id -u)" -ne 0 ] || sudo=
  command -v apt-get >/dev/null || { echo 'install.sh: needs Ubuntu 24.04 or 26.04 (apt-get)' >&2; return 1; }

  # The cloud-init/user-data.yaml packages, plus python3-apt for chart's check mode.
  local packages=(ca-certificates curl gnupg openssl git rsync tar unzip xz-utils zstd
    python3 python3-venv python3-apt jq procps acl sudo) missing=() package
  for package in "${packages[@]}"; do
    dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -qx installed ||
      missing+=("$package")
  done
  if ((${#missing[@]})); then
    $sudo apt-get update -q
    $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${missing[@]}"
  fi

  if [ -z "$ref" ]; then
    ref=$(git ls-remote --tags --refs --sort=-v:refname "$repo" 'v[0-9]*' | sed -n '1s|.*refs/tags/||p')
    [ -n "$ref" ] || { echo "install.sh: no release tag found in $repo" >&2; return 1; }
  fi
  if [ -d "$dir/.git" ]; then
    git -C "$dir" fetch -q --tags origin
    git -C "$dir" checkout -q "$ref"
  else
    git clone -q --branch "$ref" "$repo" "$dir"
  fi
  echo "Crewship $ref in $dir"

  cd "$dir"
  ./onboard.sh
  [ -f .local/host.yml ] || ./ship.sh dock "$@"
  ./ship.sh inspect
  # Check mode cannot preview tasks that depend on an earlier install, so chart
  # fails on a fresh host; it changes nothing, and launch reports real failures.
  ./ship.sh chart || echo 'install.sh: chart could not preview every change (normal on a fresh host); launching' >&2
  ./ship.sh launch
  echo 'Crewship is installed. Next: gh auth login, then sign in to omp (docs/omp.md#sign-in) and rerun install.sh.'
}

# Under `curl | bash` the script is stdin, so prompts (sudo, the new-host
# questions) read the terminal instead; without one, launch needs passwordless sudo.
if { : </dev/tty; } 2>/dev/null; then main "$@" </dev/tty; else main "$@" </dev/null; fi
