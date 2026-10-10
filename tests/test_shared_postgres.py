"""Run the service tests only inside a disposable Docker-in-Docker lab.

CREWSHIP_POSTGRES_LAB=1 enables Ansible and container operations.
"""

import concurrent.futures
import fcntl
import importlib.util
import json
import os
import select
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


def connection_url(home, project):
    result = cli(home, project)
    path = home / ".local/state/code-factory/secrets/shared-postgres" / (project + ".env")
    assert result.stdout == str(path) + "\n"
    assert result.stderr == ""
    assert path.stat().st_mode & 0o777 == 0o600
    key, url = path.read_text().strip().split("=", 1)
    assert key == "DATABASE_URL"
    assert urlsplit(url).password not in result.stdout + result.stderr
    return url


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


@pytest.mark.parametrize("available", [False, True])
def test_docker_access_check_does_not_change_resources(tmp_path, available):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("docker", "sudo"):
        command = binaries / name
        command.write_text(f"#!/bin/sh\nexit {0 if available else 1}\n")
        command.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, HELPER, "--check-docker"],
        env={**os.environ, "HOME": str(home), "PATH": str(binaries)},
        capture_output=True, text=True,
    )
    assert result.returncode == (0 if available else 1)
    if not available:
        assert "requires explicit Docker access" in result.stderr
        assert "does not grant Docker privileges" in result.stderr
    assert list(home.iterdir()) == []


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
        urls = list(pool.map(lambda _: connection_url(service, "example-app"), range(4)))
    assert len(set(urls)) == 1
    first = urls[0]
    second = connection_url(service, "another-app")
    assert query(first, "CREATE TABLE proof (n integer); INSERT INTO proof VALUES (42)").returncode == 0
    path = service / ".local/state/code-factory/secrets/shared-postgres/example-app.env"
    before = path.stat().st_mtime_ns
    assert connection_url(service, "example-app") == first
    assert path.stat().st_mtime_ns == before
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
    denied = tmp_path / "denied"
    denied.mkdir()
    for name in ("docker", "sudo"):
        executable = denied / name
        executable.write_text("#!/bin/sh\nexit 1\n")
        executable.chmod(0o755)
    denied_playbook = yaml.safe_load(playbook.read_text())
    denied_playbook[0]["vars"]["crewship_user_systemd_env"] = {"PATH": str(denied)}
    playbook.write_text(yaml.safe_dump(denied_playbook))
    rejected = subprocess.run(command, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "requires explicit Docker access" in rejected.stdout
    assert not (home / ".local/bin/crewship-db").exists()
    assert (home / ".local/state/code-factory/shared-postgres/projects-dir").read_text().strip() == str(home / "Dev/firstmate/projects")
    denied_playbook[0]["vars"]["crewship_user_systemd_env"] = {}
    playbook.write_text(yaml.safe_dump(denied_playbook))
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
    assert query(connection_url(home, "example-app"), "SELECT 1").stdout.strip() == "1"


@lab
@pytest.mark.parametrize("checkout", [
    ".treehouse/swarms-platform-test/1/swarms-platform",
    ".treehouse/firstmate-test/1/firstmate/projects/swarms-platform",
])
def test_supabase_and_postgres_seeders_do_not_rewrite_unchanged_environment(service, checkout):
    shared = service / "oss-fleet/shared-supabase"
    shared.mkdir(parents=True)
    (service / "oss-fleet/doctor").mkdir()
    (shared / "swarms-platform.env.local").write_text("# fleet-shared-supabase\nOTHER=keep\n")
    worktree = service / checkout
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: disposable\n")
    (worktree / "package.json").write_text("{}")
    installed = service / ".local/bin/crewship-db"
    installed.parent.mkdir(parents=True)
    shutil.copyfile(HELPER, installed)
    installed.chmod(0o755)
    command = ["bash", str(ROOT / "fleet/doctor/worktree-env-seed.sh")]
    environment = {**os.environ, "HOME": str(service)}
    binaries = service / "test-bin"
    binaries.mkdir()
    ready = service / "writer-ready"
    release = service / "writer-release"
    os.mkfifo(ready)
    os.mkfifo(release)
    real_install = shutil.which("install")
    assert real_install
    wrapper = binaries / "install"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, subprocess, sys\n"
        "if pathlib.Path(sys.argv[-1]).name == '.env.local':\n"
        "    pathlib.Path(sys.argv[-1]).write_text('')\n"
        f"    with open({str(ready)!r}, 'w') as signal:\n"
        "        signal.write('ready\\n')\n"
        f"    with open({str(release)!r}) as signal:\n"
        "        signal.read(1)\n"
        f"sys.exit(subprocess.call([{real_install!r}, *sys.argv[1:]]))\n"
    )
    wrapper.chmod(0o755)
    ready_fd = os.open(ready, os.O_RDWR | os.O_NONBLOCK)
    release_fd = os.open(release, os.O_RDWR | os.O_NONBLOCK)
    postgres = None
    supabase = subprocess.Popen(
        command, env={**environment, "PATH": str(binaries) + ":" + os.environ["PATH"]},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert select.select([ready_fd], [], [], 30)[0], "Supabase writer did not pause"
        assert os.read(ready_fd, 64) == b"ready\n"
        lock_path = service / ".local/state/code-factory/secrets/shared-postgres/.lock"
        with lock_path.open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        postgres = subprocess.Popen(
            [sys.executable, HELPER, "--seed"], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    finally:
        os.write(release_fd, b"x")
        os.close(release_fd)
        os.close(ready_fd)
        _, stderr = supabase.communicate(timeout=30)
        assert supabase.returncode == 0, stderr.decode()
        if postgres is not None:
            _, stderr = postgres.communicate(timeout=30)
            assert postgres.returncode == 0, stderr.decode()
    path = worktree / ".env.local"
    assert path.read_text().splitlines()[:2] == ["# fleet-shared-supabase", "OTHER=keep"]
    first = path.read_bytes(), path.stat().st_mtime_ns
    subprocess.run(command, env=environment, capture_output=True, check=True)
    assert first == (path.read_bytes(), path.stat().st_mtime_ns)
    assert list(worktree.glob(".env.local.pre-shared-*")) == []
    url = path.read_text().split("DATABASE_URL=", 1)[1].strip()
    assert query(url, "SELECT current_database()").stdout.strip() == "crewship_swarms-platform"
