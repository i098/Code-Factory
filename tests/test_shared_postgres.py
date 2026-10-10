"""Run the service tests only inside a disposable Docker-in-Docker lab.

CREWSHIP_POSTGRES_LAB=1 enables Ansible and container operations.
"""

import concurrent.futures
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "fleet/bin/crewship-db"
SPEC = importlib.util.spec_from_file_location("ship_postgres", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)
lab = pytest.mark.skipif(os.environ.get("CREWSHIP_POSTGRES_LAB") != "1", reason="disposable Docker lab only")


def cli(home, *args, check=True):
    return subprocess.run(
        [sys.executable, HELPER, *args], env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True, check=check,
    )


@pytest.mark.parametrize("enabled", [True, False, None])
def test_schema_and_legacy_profile(enabled):
    config = yaml.safe_load((ROOT / "config/default.yml").read_text())
    assert config["crewship"]["profiles"]["shared_postgres"] is False
    if enabled is None:
        config["crewship"]["profiles"].pop("shared_postgres")
    else:
        config["crewship"]["profiles"]["shared_postgres"] = enabled
    assert ship.validate_config(config) is config


@pytest.mark.parametrize("value", ["true", 1, None])
def test_schema_rejects_non_boolean(value):
    config = yaml.safe_load((ROOT / "config/default.yml").read_text())
    config["crewship"]["profiles"]["shared_postgres"] = value
    with pytest.raises(ValueError, match="profiles.shared_postgres"):
        ship.validate_config(config)


@pytest.mark.parametrize("dependency", ["docker", "firstmate"])
def test_runtime_dependencies(dependency):
    config = yaml.safe_load((ROOT / "config/default.yml").read_text())
    config["crewship"]["profiles"]["shared_postgres"] = True
    config["crewship"]["profiles"][dependency] = False
    with pytest.raises(ValueError, match="shared Postgres requires"):
        ship.validate_config(config)


def test_preview_and_deferred_start(tmp_path):
    assert "configure" in cli(tmp_path, "--apply", "--check").stdout
    assert list(tmp_path.iterdir()) == []
    assert "configure" in cli(tmp_path, "--apply", "--no-start").stdout
    config = tmp_path / ".local/state/code-factory/shared-postgres/compose.json"
    secret = tmp_path / ".local/state/code-factory/secrets/shared-postgres/superuser"
    state = config.read_bytes(), secret.read_bytes(), config.stat().st_mtime_ns, secret.stat().st_mtime_ns
    assert cli(tmp_path, "--apply", "--no-start").stdout == ""
    assert cli(tmp_path, "--apply", "--check").stdout == ""
    assert state == (config.read_bytes(), secret.read_bytes(), config.stat().st_mtime_ns, secret.stat().st_mtime_ns)
    assert secret.stat().st_mode & 0o777 == 0o600
    document = json.loads(config.read_text())
    service = document["services"]["postgres"]
    assert service["ports"] == ["127.0.0.1:25432:5432"]
    assert service["restart"] == "unless-stopped"
    assert service["image"] == "postgres:latest"
    assert document["volumes"]["data"]["name"] == "crewship-shared-postgres-data"
    assert secret.read_text().strip() not in config.read_text()


@pytest.fixture
def service(tmp_path):
    if os.environ.get("CREWSHIP_POSTGRES_LAB") != "1":
        pytest.skip("disposable Docker lab only")
    home = tmp_path / "home"
    home.mkdir()
    cli(home, "--apply")
    yield home
    subprocess.run(["docker", "compose", "-f", str(home / ".local/state/code-factory/shared-postgres/compose.json"), "down", "-v"], check=True, capture_output=True)


def query(url, sql):
    connection = urlsplit(url)
    return subprocess.run([
        "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-h", connection.hostname, "-p", str(connection.port),
        "-U", connection.username, "-d", connection.path.removeprefix("/"), "-c", sql,
    ], env={**os.environ, "PGPASSWORD": connection.password}, capture_output=True, text=True)


@lab
def test_helper_is_concurrent_idempotent_and_isolates_projects(service):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        urls = list(pool.map(lambda _: cli(service, "example-app").stdout.strip(), range(4)))
    assert len(set(urls)) == 1
    first = urls[0]
    second = cli(service, "another-app").stdout.strip()
    assert query(first, "CREATE TABLE proof (n integer); INSERT INTO proof VALUES (42)").returncode == 0
    assert cli(service, "example-app").stdout.strip() == first
    assert query(first, "SELECT n FROM proof").stdout.strip() == "42"
    assert query(second, "SELECT current_user").stdout.strip() == "crewship_another-app"
    assert query(second.rsplit("/", 1)[0] + "/crewship_example-app", "SELECT 1").returncode != 0
    assert query(first.replace(urlsplit(first).password, "wrong-password"), "SELECT 1").returncode != 0
    assert cli(service, "bad';DROP ROLE postgres;--", check=False).returncode != 0
    assert cli(service, "../traverse", check=False).returncode != 0
    assert cli(service, "--apply").stdout == ""
    status = subprocess.run(["docker", "inspect", "crewship-shared-postgres"], capture_output=True, text=True, check=True)
    container = json.loads(status.stdout)[0]
    assert container["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
    assert container["NetworkSettings"]["Ports"]["5432/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": "25432"}]


@lab
def test_seeder_keeps_other_values_and_shares_one_database(service):
    worktrees = [service / ".treehouse/example-app-abc" / str(n) / "example-app" for n in (1, 2)]
    worktrees += [service / ".treehouse/firstmate-abc/1/firstmate/projects/example-app"]
    worktrees += [service / "Dev/firstmate/projects/example-app"]
    for worktree in worktrees:
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: disposable\n")
        (worktree / ".env.local").write_text("OTHER=keep\nexport DATABASE_URL=old\n")
    cli(service, "--seed")
    contents = [(worktree / ".env.local").read_text() for worktree in worktrees]
    assert len(set(contents)) == 1
    assert contents[0].splitlines()[:2] == ["OTHER=keep", "# crewship-shared-postgres"]
    url = contents[0].split("DATABASE_URL=", 1)[1].strip()
    assert query(url, "SELECT current_database()").stdout.strip() == "crewship_example-app"
    mtimes = [(worktree / ".env.local").stat().st_mtime_ns for worktree in worktrees]
    cli(service, "--seed")
    assert mtimes == [(worktree / ".env.local").stat().st_mtime_ns for worktree in worktrees]
    assert all((worktree / ".env.local").stat().st_mode & 0o777 == 0o600 for worktree in worktrees)


@lab
def test_ansible_on_off_and_idempotence(service, tmp_path):
    home = service
    variables = {
        "crewship_repo": str(ROOT), "crewship_local_bin": str(home / ".local/bin"),
        "crewship_user_units": str(home / ".config/systemd/user"),
        "crewship_firstmate_dir": str(home / "custom-workspace/firstmate"),
        "crewship_cfg": {"home": str(home), "user": "root", "profiles": {"shared_postgres": True}},
        "crewship_group": "root", "crewship_manage_services": False,
        "crewship_become_target": False, "crewship_user_systemd_env": {},
    }
    (home / ".local/bin").mkdir(parents=True)
    # Use the real task consumer, but never start host services.
    (tmp_path / "templates").symlink_to(ROOT / "ansible/templates")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": variables,
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/shared_postgres.yml"),
                   "when": "crewship_cfg.profiles.shared_postgres | bool"}],
        "handlers": [{"name": "reload user systemd", "ansible.builtin.debug": {"msg": "deferred"}}],
    }]))
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" not in first.stdout.split("PLAY RECAP")[-1]
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" in second.stdout.split("PLAY RECAP")[-1]
    primary = home / "custom-workspace/firstmate/projects/main-project"
    primary.mkdir(parents=True)
    (primary / ".git").mkdir()
    cli(home, "--seed")
    primary_url = (primary / ".env.local").read_text().split("DATABASE_URL=", 1)[1].strip()
    assert query(primary_url, "SELECT current_database()").stdout.strip() == "crewship_main-project"
    before = {str(p.relative_to(home)): (p.read_bytes(), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    playbook_data = yaml.safe_load(playbook.read_text())
    playbook_data[0]["vars"]["crewship_cfg"]["profiles"]["shared_postgres"] = False
    playbook.write_text(yaml.safe_dump(playbook_data))
    off = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" in off.stdout.split("PLAY RECAP")[-1]
    assert before == {str(p.relative_to(home)): (p.read_bytes(), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    volume = subprocess.run(["docker", "volume", "inspect", "crewship-shared-postgres-data"], capture_output=True, text=True, check=True)
    assert json.loads(volume.stdout)[0]["Name"] == "crewship-shared-postgres-data"
    assert query(cli(home, "example-app").stdout.strip(), "SELECT 1").stdout.strip() == "1"


@lab
def test_supabase_and_postgres_seeders_do_not_rewrite_unchanged_environment(service):
    shared = service / "oss-fleet/shared-supabase"
    shared.mkdir(parents=True)
    (service / "oss-fleet/doctor").mkdir()
    (shared / "swarms-platform.env.local").write_text("# fleet-shared-supabase\nOTHER=keep\n")
    worktree = service / ".treehouse/swarms-platform-test/1/swarms-platform"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: disposable\n")
    (worktree / "package.json").write_text("{}")
    installed = service / ".local/bin/crewship-db"
    installed.parent.mkdir(parents=True)
    shutil.copyfile(HELPER, installed)
    installed.chmod(0o755)
    command = ["bash", str(ROOT / "fleet/doctor/worktree-env-seed.sh")]
    environment = {**os.environ, "HOME": str(service)}
    subprocess.run(command, env=environment, capture_output=True, check=True)
    path = worktree / ".env.local"
    first = path.read_bytes(), path.stat().st_mtime_ns
    subprocess.run(command, env=environment, capture_output=True, check=True)
    assert first == (path.read_bytes(), path.stat().st_mtime_ns)
    assert list(worktree.glob(".env.local.pre-shared-*")) == []
    url = path.read_text().split("DATABASE_URL=", 1)[1].strip()
    assert query(url, "SELECT current_database()").stdout.strip() == "crewship_swarms-platform"
