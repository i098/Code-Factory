import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("factory_config", ROOT / "scripts/factory.py")
factory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(factory)


@pytest.fixture
def configuration():
    return yaml.safe_load((ROOT / "config/default.yml").read_text())


def test_valid_configuration_is_accepted_by_real_schema(configuration):
    assert factory.validate_config(configuration) is configuration


@pytest.mark.parametrize(
    "workspace", ["/home/other/Dev", "/home/coder/../other/Dev", "/home/coder"]
)
def test_workspace_cannot_escape_operator_home(configuration, workspace):
    configuration["factory"]["workspace"] = workspace
    with pytest.raises(ValueError, match="workspace"):
        factory.validate_config(configuration)


def test_invalid_secret_field_is_rejected_without_echoing_value(configuration):
    private_value = "PRIVATE_VALUE_MUST_NOT_APPEAR_IN_DIAGNOSTICS"
    configuration["factory"]["api_key"] = private_value
    with pytest.raises(ValueError) as failure:
        factory.validate_config(configuration)
    assert private_value not in str(failure.value)


def test_firstmate_cannot_silently_omit_its_agent_dependencies(configuration):
    configuration["factory"]["profiles"]["agents"] = False
    with pytest.raises(ValueError, match="Firstmate requires"):
        factory.validate_config(configuration)


def test_firstmate_revision_pin_is_rejected(configuration):
    # The checkout tracks upstream main; a sha pin would silently freeze a
    # host on an old Firstmate, so the schema refuses the key outright.
    configuration["factory"]["firstmate"]["revision"] = "0" * 40
    with pytest.raises(ValueError):
        factory.validate_config(configuration)


def test_fleet_guards_require_docker_and_firstmate(configuration):
    configuration["factory"]["profiles"]["fleet_guards"] = True
    configuration["factory"]["profiles"]["docker"] = False
    with pytest.raises(ValueError, match="fleet guards require"):
        factory.validate_config(configuration)


def test_fleet_guards_accept_the_default_document_when_enabled(configuration):
    configuration["factory"]["profiles"]["fleet_guards"] = True
    assert factory.validate_config(configuration) is configuration


def test_fleet_guards_require_browsers_block(configuration):
    configuration["factory"]["profiles"]["fleet_guards"] = True
    configuration["factory"].pop("browsers", None)
    with pytest.raises(ValueError, match="obscura"):
        factory.validate_config(configuration)


def test_browsers_valid_block_accepted(configuration):
    assert factory.validate_config(configuration) is configuration


def test_fleet_fixture_archive_cannot_traverse(configuration):
    configuration["factory"]["profiles"]["fleet_guards"] = True
    configuration["factory"]["fleet"]["fixture_archive"] = "/home/coder/../root/db.tgz"
    with pytest.raises(ValueError, match="traverse"):
        factory.validate_config(configuration)


def test_unknown_fleet_field_is_rejected(configuration):
    configuration["factory"]["fleet"]["allow_migrations"] = True
    with pytest.raises(ValueError):
        factory.validate_config(configuration)


def test_bad_polling_window_cannot_disable_idle_accrual(configuration):
    configuration["factory"]["browser_prune"]["max_gap_seconds"] = 120
    with pytest.raises(ValueError, match="observation intervals"):
        factory.validate_config(configuration)


def test_init_preserves_existing_local_configuration(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / path, tmp_path / path)
    shutil.copyfile(ROOT / "toolchain.lock.json", tmp_path / "toolchain.lock.json")
    monkeypatch.setattr(factory, "ROOT", tmp_path)
    args = argparse.Namespace(user="coder", home="/home/coder", container=True)
    factory.initialize(args)
    local = tmp_path / ".local/host.yml"
    first = local.read_bytes()
    config = factory.load_config(local)["factory"]
    assert not config["start_services"] and not config["profiles"]["docker"]
    assert config["profiles"]["agents"]
    with pytest.raises(FileExistsError):
        factory.initialize(args)
    assert local.read_bytes() == first


def test_root_operator_is_rejected_before_config_is_written(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / path, tmp_path / path)
    shutil.copyfile(ROOT / "toolchain.lock.json", tmp_path / "toolchain.lock.json")
    monkeypatch.setattr(factory, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="non-root"):
        factory.initialize(argparse.Namespace(user="root", home="/home/root", container=False))
    assert not (tmp_path / ".local/host.yml").exists()


def fake_omp(launches, models=json.dumps({"models": [{"id": "model"}]}), exits=lambda n: 0):
    def run(command, **kwargs):
        if command[1:] == ["models", "--json"]:
            return subprocess.CompletedProcess(command, 0, models)
        launches.append(command)
        return subprocess.CompletedProcess(command, exits(len(launches)))

    return run


@pytest.mark.parametrize(
    "tty,ci,launched", [(False, "", False), (True, "true", False), (True, "", True)]
)
def test_questions_launch_only_on_an_interactive_terminal_outside_ci(
    configuration, tmp_path, monkeypatch, capsys, tty, ci, launched
):
    configuration["factory"].update(
        user=factory.pwd.getpwuid(factory.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    configuration["factory"]["firstmate"].pop("checklist", None)
    launches = []
    monkeypatch.setattr(factory.sys.stdin, "isatty", lambda: tty)
    monkeypatch.setenv("CI", ci)
    monkeypatch.setattr(factory.subprocess, "run", fake_omp(launches))
    assert factory.questions(configuration) == 0
    assert [command[0] for command in launches] == [tmp_path / ".local/bin/omp"] * launched
    skipped = capsys.readouterr().out.count("rerun ./factory apply interactively")
    assert skipped == (0 if launched else 1)


def test_second_apply_does_not_reopen_the_questions(configuration, tmp_path, monkeypatch, capsys):
    configuration["factory"].update(
        user=factory.pwd.getpwuid(factory.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    configuration["factory"]["firstmate"].pop("checklist", None)
    launches = []
    monkeypatch.setattr(factory, "load_config", lambda path: configuration)
    monkeypatch.setattr(factory, "provision", lambda document, check: 0)
    monkeypatch.setattr(factory.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        factory.subprocess, "run", fake_omp(launches, exits=lambda n: 0 if n > 1 else 1)
    )
    monkeypatch.setattr(
        factory.sys, "argv", ["factory", "apply", "--config", str(tmp_path / "host.yml")]
    )
    marker = tmp_path / ".local/share/code-factory/new-host-questions-done"
    assert factory.main() == 0
    assert not marker.exists()
    assert "New-host questions did not complete (omp exited 1)" in capsys.readouterr().out
    assert factory.main() == 0
    assert [command[0] for command in launches] == [tmp_path / ".local/bin/omp"] * 2
    assert marker.is_file()
    capsys.readouterr()
    assert factory.main() == 0
    assert len(launches) == 2
    assert f"{marker} exists); delete it and rerun" in capsys.readouterr().out


def test_questions_wait_for_an_omp_sign_in(configuration, tmp_path, monkeypatch, capsys):
    configuration["factory"].update(
        user=factory.pwd.getpwuid(factory.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    launches = []
    monkeypatch.setattr(factory.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        factory.subprocess, "run", fake_omp(launches, models=json.dumps({"models": []}))
    )
    assert factory.questions(configuration) == 0
    assert launches == []
    assert not (tmp_path / ".local/share/code-factory/new-host-questions-done").exists()
    assert "sign in to omp with /login" in capsys.readouterr().out


def test_another_accounts_apply_skips_questions_without_reading_the_unreadable_home(
    configuration, tmp_path, monkeypatch, capsys
):
    home = tmp_path / "coder"
    home.mkdir(mode=0o000)
    configuration["factory"].update(user="another-account", home=str(home))
    monkeypatch.setattr(factory.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **k: pytest.fail("launched"))
    try:
        assert factory.questions(configuration) == 0
    finally:
        home.chmod(0o700)
    assert "rerun ./factory apply interactively as another-account" in capsys.readouterr().out


def test_apply_warns_when_firstmate_still_tracks_the_stale_fork(
    configuration, tmp_path, monkeypatch, capsys
):
    configuration["factory"]["firstmate"]["url"] = factory.STALE_FIRSTMATE_URL
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(configuration))
    monkeypatch.setattr(factory, "provision", lambda document, check: 0)
    monkeypatch.setattr(factory.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(factory.sys, "argv", ["factory", "apply", "--config", str(host)])
    assert factory.main() == 0
    output = capsys.readouterr()
    assert output.err.startswith("WARNING: firstmate.url is the stale fork")
    assert "rerun ./factory apply interactively" in output.out


def _verify_firstmate(tmp_path, origin, configured):
    checkout = tmp_path / "firstmate"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(checkout)]
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "c"], check=True)
    subprocess.run([*git, "remote", "add", "origin", origin], check=True)
    head = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    playbook = tmp_path / "verify.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/verify.yml")}
                    ],
                }
            ]
        )
    )
    variables = {
        "factory_account_ready": True,
        "factory_become_target": False,
        "factory_user_env": {},
        "factory_manage_services": False,
        "factory_user_units": str(tmp_path),
        "factory_docker_group_users": [],
        "factory_firstmate_dir": str(checkout),
        "factory_firstmate_target": head,
        "factory_cfg": {
            "user": "coder",
            "profiles": {
                "agents": False,
                "firstmate": True,
                "docker": False,
                "tailscale": False,
                "desktop": False,
            },
            "firstmate": {"url": configured},
        },
    }
    return subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--start-at-task",
            "Read the Firstmate origin URL",
            "--extra-vars",
            json.dumps(variables),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_verify_fails_when_firstmate_origin_is_not_the_configured_url(tmp_path):
    upstream = "https://github.com/kunchenguid/firstmate.git"
    result = _verify_firstmate(tmp_path, factory.STALE_FIRSTMATE_URL, upstream)
    assert result.returncode != 0
    assert "updated the wrong repository" in result.stdout


def test_verify_passes_when_firstmate_origin_is_the_configured_url(tmp_path):
    upstream = "https://github.com/kunchenguid/firstmate.git"
    result = _verify_firstmate(tmp_path, upstream, upstream)
    assert result.returncode == 0, result.stdout


def _ensure_status_row(tmp_path, config):
    playbook = tmp_path / "agents.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/agents.yml")}
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--start-at-task",
            "Read the omp config for the status row keys",
            "--extra-vars",
            json.dumps({"factory_omp_config": str(config), "ansible_become": False}),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def test_existing_omp_config_gets_the_status_row_keys_once(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "# the account's own\n"
        "theme: {dark: titanium}\n"
        "statusLine:\n"
        "  preset: custom\n"
        "  leftSegments: [path, git]\n"
        "  showHookStatus: true\n"
        "  separator: plain\n"
        "providers:\n"
        "  anthropic: {serverSideFallback: false}\n"
    )
    config.chmod(0o600)
    assert _ensure_status_row(tmp_path, config) == 1
    assert yaml.safe_load(config.read_text()) == {
        "theme": {"dark": "titanium"},
        "statusLine": {
            "preset": "custom",
            "leftSegments": ["path", "git", "status"],
            "showHookStatus": False,
            "separator": "plain",
        },
        "providers": {"anthropic": {"serverSideFallback": False}},
    }
    assert config.stat().st_mode & 0o777 == 0o600
    written = config.read_text()
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == written


def test_omp_config_that_has_the_status_row_keys_is_left_alone(tmp_path):
    config = tmp_path / "config.yml"
    seed = (ROOT / "config/omp.yml").read_text()
    config.write_text(seed)
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == seed


def test_absent_omp_config_is_not_created_by_the_status_row_step(tmp_path):
    config = tmp_path / "config.yml"
    assert _ensure_status_row(tmp_path, config) == 0
    assert not config.exists()
