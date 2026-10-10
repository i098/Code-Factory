"""tasks/fleet_units.yml retires the flotilla-* units and installs crewship-*.

Drives the real task file and group_vars with ansible-playbook against a
throwaway home, start_services false, so no systemctl runs.
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


def apply(home, *flags, start_services=False):
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
                    "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/fleet_units.yml")}],
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
        "crewship": {"user": getpass.getuser(), "home": str(home), "start_services": start_services},
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
    assert "flotilla-shared-supabase.service" not in stops
    assert stops.index("flotilla-shared-supabase-check.timer") < stops.index("flotilla-docker-guard.service")
    assert "--user reset-failed flotilla-shared-supabase.service" in log
