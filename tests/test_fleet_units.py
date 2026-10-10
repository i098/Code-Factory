"""Fleet task fixtures write only to a throwaway home.

External commands use local stubs. No host playbook or real systemd/Docker
operation runs; the shared stack on the test host is never touched.
"""

import getpass
import grp
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
OLD = [
    "flotilla-shared-supabase.service",
    "flotilla-docker-guard.service",
    "flotilla-storage-guard.service",
    "flotilla-storage-guard.timer",
    "flotilla-shared-supabase-check.timer",
    "flotilla-worktree-env-seed.path",
]


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    units = home / ".config/systemd/user"
    for wants in ("default.target.wants", "timers.target.wants"):
        (units / wants).mkdir(parents=True)
    for unit in OLD:
        (units / unit).write_text("[Unit]\n")
        wants = "timers.target.wants" if unit.endswith(".timer") else "default.target.wants"
        (units / wants / unit).symlink_to(units / unit)
    doctor = home / "oss-fleet/doctor"
    doctor.mkdir(parents=True)
    (doctor / "docker-guard-allow.txt").write_text("project:shared\n")
    (doctor / "docker-guard.log").write_text("kept\n")
    return home


def apply(
    home, *flags, start_services=False, shared_supabase=True, fleet_guards=True, scripts=False
):
    playbook = home.parent / "units.yml"
    # Like site.yml, the playbook directory carries templates/.
    if not (home.parent / "templates").exists():
        (home.parent / "templates").symlink_to(ROOT / "ansible/templates")
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars_files": [str(ROOT / "ansible/group_vars/all.yml")],
                    "tasks": (
                        [
                            {
                                "ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/fleet_guards.yml"),
                                "when": "crewship_cfg.profiles.fleet_guards | bool",
                            },
                            {
                                "ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/shared_supabase.yml"),
                                "when": "crewship_cfg.profiles.shared_supabase | bool",
                            },
                        ] if scripts else []
                    ) + [{
                        "ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/fleet_units.yml"),
                        "when": "(crewship_cfg.profiles.fleet_guards | bool) or (crewship_cfg.profiles.shared_supabase | bool)",
                    }],
                    "handlers": [
                        {"name": "reload", "ansible.builtin.debug": {"msg": "reload"}, "listen": "reload user systemd"},
                        {"name": "timers", "ansible.builtin.debug": {"msg": "timers"}, "listen": "restart fleet timers"},
                    ],
                }
            ]
        )
    )
    variables = {
        "ansible_become": False,
        "crewship_repo": str(ROOT),
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_become_target": False,
        "crewship_latest": {"supabase": "1.2.3"},
        "crewship": {
            "user": getpass.getuser(), "home": str(home), "start_services": start_services,
            "profiles": {"fleet_guards": fleet_guards, "shared_supabase": shared_supabase},
        },
    }
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables), *flags],
        cwd=home.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def names(home):
    units = home / ".config/systemd/user"
    return sorted(str(p.relative_to(units)) for p in units.rglob("*") if not p.is_dir())


def test_an_upgraded_host_ends_with_only_the_crewship_units_and_a_second_apply_changes_nothing(home):
    assert apply(home, "--check") > 0
    assert sum("flotilla-" in n for n in names(home)) == 2 * len(OLD)

    assert apply(home) > 0
    installed = names(home)
    assert not [n for n in installed if "flotilla" in n]
    assert "crewship-docker-guard.timer" in installed
    assert "timers.target.wants/crewship-docker-guard.timer" in installed
    assert "default.target.wants/crewship-shared-supabase.service" in installed
    assert all(Path(n).name.startswith("crewship-") for n in installed)
    doctor = home / "oss-fleet/doctor"
    assert not (doctor / "docker-guard-allow.txt").exists()
    assert (doctor / "docker-guard.log").read_text() == "kept\n"
    assert apply(home) == 0
    assert names(home) == installed


def test_retiring_the_old_units_never_stops_the_shared_supabase_stack(home):
    bin_dir = home / ".local/bin"
    bin_dir.mkdir(parents=True)
    calls = home / "systemctl.calls"
    stub = bin_dir / "systemctl"
    stub.write_text(
        f'#!/bin/sh\necho "$*" >> {calls}\n'
        'case "$*" in *" show "*) printf "LoadState=loaded\\nActiveState=active\\nSubState=running\\n" ;; esac\n'
    )
    stub.chmod(0o755)

    apply(home, start_services=True)

    log = calls.read_text().splitlines()
    stops = [line.split()[-1] for line in log if " stop " in f" {line} "]

    calls.write_text("")
    apply(home, start_services=True, shared_supabase=False)
    assert not any(
        "supabase" in line or "worktree-env-seed" in line
        for line in calls.read_text().splitlines()
    )
    assert "flotilla-shared-supabase.service" not in stops
    assert stops.index("flotilla-shared-supabase-check.timer") < stops.index("flotilla-docker-guard.service")
    assert "--user reset-failed flotilla-shared-supabase.service" in log


def test_disabling_supabase_leaves_its_old_and_current_units_unmanaged(home):
    apply(home)
    units = home / ".config/systemd/user"
    preserved = {
        n: (units / n).read_bytes()
        for n in names(home)
        if "supabase" in n or "worktree-env-seed" in n
    }
    # Include legacy units: a guards-only apply must not retire these either.
    for name in ("flotilla-shared-supabase.service", "flotilla-shared-supabase-check.timer",
                 "flotilla-worktree-env-seed.path"):
        (units / name).write_text("legacy\n")
        preserved[name] = b"legacy\n"
    shared = home / "oss-fleet/shared-supabase"
    shared.mkdir()
    fixture = shared / "fixture"
    fixture.write_text("keep data\n")
    assert apply(home, shared_supabase=False) == 0
    assert {n: (units / n).read_bytes() for n in preserved} == preserved
    assert fixture.read_text() == "keep data\n"
    assert apply(home, shared_supabase=False) == 0


@pytest.mark.parametrize("fleet_guards", [False, True])
def test_default_off_writes_no_supabase_assets_or_units(tmp_path, fleet_guards):
    home = tmp_path / "home"
    home.mkdir()
    apply(home, scripts=True, shared_supabase=False, fleet_guards=fleet_guards)
    assert not (home / "oss-fleet/shared-supabase").exists()
    assert not (home / ".local/bin/supabase").exists()
    assert not (home / "oss-fleet/doctor/worktree-env-seed.sh").exists()
    assert not any("supabase" in n or "worktree-env-seed" in n for n in names(home))
    assert apply(home, scripts=True, shared_supabase=False, fleet_guards=fleet_guards) == 0


def test_opt_in_installs_the_stack_and_a_second_apply_changes_nothing(tmp_path):
    home = tmp_path / "home"
    bin_dir = home / ".local/bin"
    bin_dir.mkdir(parents=True)
    calls = home / "external.calls"
    # The installed CLI answers --version only. No stack can start here.
    npm = bin_dir / "npm"
    npm.write_text(
        '#!/bin/sh\n'
        'test "$1" = install && test "$2" = --prefix || exit 1\n'
        'mkdir -p "$3/node_modules/.bin"\n'
        'printf \'#!/bin/sh\\ntest "$1" = --version || exit 1\\necho 1.2.3\\n\' '
        '> "$3/node_modules/.bin/supabase"\n'
        'chmod 755 "$3/node_modules/.bin/supabase"\n'
        f'echo npm-install >> "{calls}"\n'
    )
    docker = bin_dir / "docker"
    docker.write_text(
        f'#!/bin/sh\necho "$*" >> "{calls}"\n'
        'test "$1 $2" = "volume inspect"\n'
    )
    npm.chmod(0o755)
    docker.chmod(0o755)
    assert apply(home, scripts=True, fleet_guards=False) > 0
    shared = home / "oss-fleet/shared-supabase"
    assert (shared / "supabase/config.toml").is_file()
    assert (shared / "check.sh").stat().st_mode & 0o111
    assert (shared / "guard.sql").is_file()
    assert (home / ".local/bin/supabase").is_file()
    assert (home / "oss-fleet/doctor/worktree-env-seed.sh").is_file()
    assert "default.target.wants/crewship-shared-supabase.service" in names(home)
    assert "timers.target.wants/crewship-shared-supabase-check.timer" in names(home)
    assert "default.target.wants/crewship-worktree-env-seed.path" in names(home)
    assert not (home / "oss-fleet/doctor/docker-guard.sh").exists()
    assert apply(home, scripts=True, fleet_guards=False) == 0
    log = calls.read_text().splitlines()
    assert log.count("npm-install") == 1
    assert all(line == "npm-install" or line.startswith("volume inspect ") for line in log)
    before = {p: p.read_bytes() for p in shared.rglob("*") if p.is_file()}
    calls.write_text("")
    assert apply(home, scripts=True, shared_supabase=False, fleet_guards=False) == 0
    assert calls.read_text() == ""
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize(
    "prefixes, stop_code, systemd_failure",
    [
        (("crewship", "flotilla"), 0, ""),
        (("crewship", "flotilla"), 7, ""),
        (("crewship",), 0, ""),
        (("flotilla",), 0, ""),
        (("crewship", "flotilla"), 0, "unreachable"),
        *[
            (("crewship", "flotilla"), 0, f"{prefix}-{suffix}")
            for prefix in ("crewship", "flotilla")
            for suffix in (
                "shared-supabase.service", "shared-supabase-check.service",
                "shared-supabase-check.timer", "worktree-env-seed.service",
                "worktree-env-seed.timer", "worktree-env-seed.path",
            )
        ],
    ],
)
def test_manual_removal_stops_the_stack_before_deleting_files(
    tmp_path, prefixes, stop_code, systemd_failure
):
    home = tmp_path / "home"
    shared = home / "oss-fleet/shared-supabase"
    cli = shared / "node_modules/.bin/supabase"
    cli.parent.mkdir(parents=True)
    bin_dir = home / ".local/bin"
    bin_dir.mkdir(parents=True)
    running = home / "running-units"
    running.mkdir()
    units = home / ".config/systemd/user"
    for wants in ("default.target.wants", "timers.target.wants"):
        (units / wants).mkdir(parents=True)
    (home / "oss-fleet/doctor").mkdir(parents=True)
    suffixes = [
        "shared-supabase.service", "shared-supabase-check.service",
        "shared-supabase-check.timer", "worktree-env-seed.service",
        "worktree-env-seed.timer", "worktree-env-seed.path",
    ]
    installed = []
    for prefix in prefixes:
        for suffix in suffixes:
            name = f"{prefix}-{suffix}"
            path = units / name
            path.write_text("[Unit]\n")
            installed.append(path)
            wants = "timers.target.wants" if suffix.endswith(".timer") else "default.target.wants"
            link = units / wants / name
            link.symlink_to(path)
            installed.append(link)
            if suffix != "shared-supabase.service":
                (running / name).touch()
    for path in [
        bin_dir / "supabase", home / "oss-fleet/doctor/worktree-env-seed.sh",
        shared / "check.sh", shared / "guard.sql",
    ]:
        path.write_text("installed\n")
        installed.append(path)
    cli.write_text(
        '#!/bin/sh\n'
        'touch "$HOME/cli-called"\n'
        'test "$#" = 3 && test "$1" = stop && test "$2" = --workdir && '
        'test "$3" = "$HOME/oss-fleet/shared-supabase" || exit 8\n'
        'for unit in "$HOME/running-units/"*; do test ! -e "$unit" || exit 9; done\n'
        f'for prefix in {" ".join(prefixes)}; do\n'
        '  test -f "$HOME/.config/systemd/user/$prefix-shared-supabase.service" || exit 10\n'
        'done\n'
        f'exit_code={stop_code}\n'
        'test "$exit_code" = 0 || exit "$exit_code"\n'
        'rm "$HOME/stack-running"\n'
    )
    cli.chmod(0o755)
    installed.append(cli)
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        '#!/bin/sh\n'
        'test "$SYSTEMCTL_FAILURE" != unreachable || exit 11\n'
        'test "$1" = --user || exit 1\nshift\n'
        'case "$1" in\n'
        'show)\n'
        '  if test -f "$HOME/.config/systemd/user/$2"; then\n'
        '    echo loaded\n'
        '  else\n'
        '    echo not-found\n'
        '  fi\n'
        '  exit 0 ;;\n'
        'disable) shift 2\n'
        '  for unit; do\n'
        '    rm -f "$HOME/.config/systemd/user/"*.wants/"$unit"\n'
        '  done ;;\n'
        'stop) shift ;;\n'
        'daemon-reload) exit 0 ;;\n'
        '*) exit 1 ;;\nesac\n'
        'for unit; do\n'
        '  test "$unit" != "$SYSTEMCTL_FAILURE" || exit 12\n'
        '  test -f "$HOME/.config/systemd/user/$unit" || exit 5\n'
        '  rm -f "$HOME/running-units/$unit"\n'
        'done\n'
    )
    systemctl.chmod(0o755)
    stack = home / "stack-running"
    stack.touch()
    volume = home / "fixture-volume"
    volume.write_text("fixture data\n")
    before = {path: path.read_bytes() for path in installed}
    commands = (ROOT / "docs/fleet-guards.md").read_text().split("### Manual removal", 1)[1]
    commands = commands.split("```bash\n", 1)[1].split("```", 1)[0]
    result = subprocess.run(
        ["bash", "-c", commands],
        env={
            **os.environ, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SYSTEMCTL_FAILURE": systemd_failure,
        },
        capture_output=True,
        text=True,
    )
    expected_code = 11 if systemd_failure == "unreachable" else 12 if systemd_failure else stop_code
    assert result.returncode == expected_code, result.stderr
    assert (home / "cli-called").exists() == (not systemd_failure)
    assert stack.exists() == bool(expected_code)
    if expected_code:
        assert {path: path.read_bytes() for path in installed} == before
        assert all(path.is_symlink() for path in installed if ".wants" in str(path.parent))
    else:
        assert all(not path.exists() and not path.is_symlink() for path in installed)
    assert volume.read_text() == "fixture data\n"
