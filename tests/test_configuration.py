import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
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


def test_legacy_obscura_keys_are_ignored_with_one_warning_and_apply_proceeds(
    configuration, tmp_path, monkeypatch, capsys
):
    legacy = tmp_path / "legacy.yml"
    current = tmp_path / "current.yml"
    current.write_text(yaml.safe_dump(configuration))
    configuration["factory"]["browsers"].update(obscura_version="0.2.2", obscura_sha256="c" * 64)
    legacy.write_text(yaml.safe_dump(configuration))
    provisioned = []
    monkeypatch.setattr(
        factory, "provision", lambda document, check: provisioned.append(check) or 0
    )
    monkeypatch.setattr(factory, "questions", lambda document: 0)
    for host in (current, legacy):
        monkeypatch.setattr(factory.sys, "argv", ["factory", "apply", "--config", str(host)])
        assert factory.main() == 0
    warning = capsys.readouterr().err
    assert provisioned == [False, False]
    assert warning.count("WARNING") == 1
    assert "obscura_version" in warning and "obscura_sha256" in warning
    assert "no longer used" in warning


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


def _run_agents(tmp_path, start_at, **variables):
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
                    "handlers": [
                        {
                            "name": "no-mistakes daemon restart required",
                            "ansible.builtin.debug": {"msg": "restart reported"},
                        }
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
            start_at,
            "--extra-vars",
            json.dumps({"ansible_become": False, **variables}),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def _ensure_status_row(tmp_path, config):
    return _run_agents(
        tmp_path,
        "Read the omp config for the status row keys",
        factory_omp_config=str(config),
        factory_acpx_config=str(tmp_path / "absent-acpx.json"),
    )


def _ensure_acpx_default(tmp_path, config):
    return _run_agents(
        tmp_path, "Read the acpx config for the default agent", factory_acpx_config=str(config)
    )


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


@pytest.mark.parametrize(
    "text",
    [
        "theme: {dark: titanium}\n",
        "statusLine:\n  preset: default\n  showHookStatus: true\n",
        "statusLine:\n  leftSegments: [path, git]\n  showHookStatus: true\n",
    ],
)
def test_omp_config_without_the_custom_preset_is_left_alone(tmp_path, text):
    config = tmp_path / "config.yml"
    config.write_text(text)
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == text


def test_absent_omp_config_is_not_created_by_the_status_row_step(tmp_path):
    config = tmp_path / "config.yml"
    assert _ensure_status_row(tmp_path, config) == 0
    assert not config.exists()


def test_acpx_config_that_still_defaults_to_codex_gets_omp_once(tmp_path):
    config = tmp_path / "config.json"
    seed = json.loads((ROOT / "config/acpx.json").read_text())
    config.write_text(json.dumps({**seed, "defaultAgent": "codex", "ttl": 900}))
    config.chmod(0o600)
    assert _ensure_acpx_default(tmp_path, config) == 1
    assert json.loads(config.read_text()) == {**seed, "ttl": 900}
    assert config.stat().st_mode & 0o777 == 0o600
    written = config.read_text()
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == written


@pytest.mark.parametrize("text", ['{"defaultAgent": "claude"}\n', '{"ttl": 300}\n'])
def test_acpx_config_with_another_default_is_left_alone(tmp_path, text):
    config = tmp_path / "config.json"
    config.write_text(text)
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == text


def test_seeded_acpx_config_defaults_to_omp_and_absent_one_is_not_created(tmp_path):
    config = tmp_path / "config.json"
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert not config.exists()
    seed = (ROOT / "config/acpx.json").read_text()
    config.write_text(seed)
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == seed


PI_AGENT = {
    "agent": ["pi", "acp:omp"],
    "agent_config": {"pi": {"model": "anthropic/claude-sonnet-5-5", "effort": "high"}},
}


def _set_pipeline_agent(tmp_path, rc):
    """Runs the agent step with the adapter check's exit code; returns the changed count."""
    return _run_agents(
        tmp_path,
        "Read the no-mistakes config for the pipeline agent",
        factory_cfg={"home": str(tmp_path)},
        factory_omp_as_pi_dir="/w",
        factory_pi_adapter={"rc": rc, "stdout": "pi.go changed"},
        factory_omp_config=str(tmp_path / "absent-omp.yml"),
        factory_acpx_config=str(tmp_path / "absent-acpx.json"),
    )


def test_verified_pi_adapter_moves_the_seeded_agent_to_pi_once(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text((ROOT / "config/no-mistakes.yaml").read_text() + "log_level: info\n")
    assert _set_pipeline_agent(tmp_path, rc=0) == 1
    assert yaml.safe_load(config.read_text()) == {
        **PI_AGENT,
        "agent_path_override": {"pi": "/w/omp-as-pi"},
        "log_level": "info",
    }
    written = config.read_text()
    assert _set_pipeline_agent(tmp_path, rc=0) == 0
    assert config.read_text() == written


def test_a_host_already_on_pi_moves_from_xhigh_to_high_once(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    previous = {
        **PI_AGENT,
        "agent_config": {"pi": {"model": "anthropic/claude-sonnet-5-5", "effort": "xhigh"}},
        "agent_path_override": {"pi": "/w/omp-as-pi"},
    }
    config.write_text(yaml.safe_dump(previous))
    assert _set_pipeline_agent(tmp_path, rc=0) == 1
    assert yaml.safe_load(config.read_text())["agent_config"] == PI_AGENT["agent_config"]
    assert _set_pipeline_agent(tmp_path, rc=0) == 0


def test_a_pin_mismatch_moves_the_agent_to_acp_omp_alone(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({**PI_AGENT, "agent_path_override": {"pi": "/w/omp-as-pi"}}))
    assert _set_pipeline_agent(tmp_path, rc=1) == 1
    assert yaml.safe_load(config.read_text())["agent"] == ["acp:omp"]
    seed = (ROOT / "config/no-mistakes.yaml").read_text()
    config.write_text(seed)
    assert _set_pipeline_agent(tmp_path, rc=1) == 0
    assert config.read_text() == seed


@pytest.mark.parametrize("rc", [2, 127])
def test_an_inconclusive_adapter_check_leaves_the_agent_setting_alone(tmp_path, rc):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    for text in (
        yaml.safe_dump({**PI_AGENT, "agent_path_override": {"pi": "/w/omp-as-pi"}}),
        (ROOT / "config/no-mistakes.yaml").read_text(),
    ):
        config.write_text(text)
        assert _set_pipeline_agent(tmp_path, rc=rc) == 0
        assert config.read_text() == text


def test_operator_chosen_agent_is_left_alone(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text("agent: [claude]\n")
    assert _set_pipeline_agent(tmp_path, rc=0) == 0
    assert config.read_text() == "agent: [claude]\n"


def _managed_environment(tmp_path, fleet_guards, release="1.0.0"):
    variables = {
        "factory_cfg": {"home": str(tmp_path), "profiles": {"fleet_guards": fleet_guards}},
        "factory_latest": {"chrome-devtools-mcp": release},
    }
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible",
            "localhost",
            "-i",
            "localhost,",
            "-c",
            "local",
            "-m",
            "ansible.builtin.debug",
            "-a",
            "var=factory_managed_shell_env",
            "-e",
            f"@{ROOT / 'ansible/group_vars/all.yml'}",
            "-e",
            json.dumps(variables),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return json.loads(result.stdout.split("=>", 1)[1])["factory_managed_shell_env"]


@pytest.mark.parametrize("fleet_guards", [False, True])
def test_the_managed_environment_never_carries_a_process_wide_runtime_limit(tmp_path, fleet_guards):
    assert set(_managed_environment(tmp_path, fleet_guards)) == {"CHROME_DEVTOOLS_AXI_MCP_PATH"}


def test_a_new_chrome_devtools_mcp_release_leaves_the_managed_environment_unchanged(tmp_path):
    before = _managed_environment(tmp_path, True, "1.0.0")
    assert _managed_environment(tmp_path, True, "1.1.0") == before
    assert before["CHROME_DEVTOOLS_AXI_MCP_PATH"].endswith(
        "/chrome-devtools-mcp/current/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"
    )


def _ansible(tmp_path, *argv, wrapper=()):
    return subprocess.run(
        [*wrapper, Path(sys.executable).parent / argv[0], *argv[1:]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def _installer_also(tmp_path, start_services=True, fleet_guards=False, fleet_browsers=False):
    variables = {
        "factory_cfg": {
            "start_services": start_services,
            "profiles": {
                "agents": False,
                "fleet_guards": fleet_guards,
                "fleet_browsers": fleet_browsers,
            },
            "browser_prune": {"enabled": False},
        }
    }
    result = _ansible(
        tmp_path,
        "ansible",
        "localhost",
        "-i",
        "localhost,",
        "-c",
        "local",
        "-m",
        "ansible.builtin.debug",
        "-a",
        "var=factory_installer_also",
        "-e",
        f"@{ROOT / 'ansible/group_vars/all.yml'}",
        "-e",
        json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout
    return json.loads(result.stdout.split("=>", 1)[1])["factory_installer_also"]


@pytest.mark.parametrize("start_services", [True, False])
def test_koncreet_is_resolved_only_on_hosts_that_start_services(tmp_path, start_services):
    assert ("koncreet" in _installer_also(tmp_path, start_services)) is start_services


@pytest.mark.parametrize("fleet_guards", [False, True])
@pytest.mark.parametrize("fleet_browsers", [False, True])
def test_each_fleet_profile_resolves_only_its_own_release(tmp_path, fleet_guards, fleet_browsers):
    # The browser ladder must not depend on the Supabase CLI resolving, and
    # fleet_guards keeps provisioning the ladder it always has.
    also = _installer_also(tmp_path, fleet_guards=fleet_guards, fleet_browsers=fleet_browsers)
    assert ("obscura" in also) is (fleet_guards or fleet_browsers)
    assert ("supabase" in also) is fleet_guards


def _koncreet_settings(tmp_path, tailscale, apply_user):
    destination = tmp_path / "koncreet.conf"
    variables = {
        "ansible_user_id": apply_user,
        "ansible_user_dir": "/root" if apply_user == "root" else f"/home/{apply_user}",
        "factory_cfg": {"user": "coder", "profiles": {"tailscale": tailscale}},
        "factory_koncreet_config": "/etc/koncreet.conf",
    }
    result = _ansible(
        tmp_path,
        "ansible",
        "localhost",
        "-i",
        "localhost,",
        "-c",
        "local",
        "-m",
        "ansible.builtin.template",
        "-a",
        f"src={ROOT / 'ansible/templates/koncreet.conf.j2'} dest={destination}",
        "-e",
        json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout
    return dict(
        line.split("=", 1)
        for line in destination.read_text().splitlines()
        if line and not line.startswith("#")
    )


@pytest.mark.parametrize(
    ("tailscale", "apply_user", "ports", "sudo_user"),
    [
        (True, "operator", "41641/udp", "operator"),
        (False, "operator", None, "operator"),
        (True, "coder", "41641/udp", None),
        (False, "root", None, None),
    ],
)
def test_koncreet_config_follows_the_tailscale_profile_and_never_makes_the_factory_user_sudo(
    tmp_path, tailscale, apply_user, ports, sudo_user
):
    settings = _koncreet_settings(tmp_path, tailscale, apply_user)
    assert settings["modules"] == "baseline,firewall,fail2ban,updates"
    assert settings.get("firewall_ports") == ports
    assert settings.get("user") == sudo_user
    assert settings.get("pubkey_file") == (
        f"/home/{sudo_user}/.ssh/authorized_keys" if sudo_user else None
    )


def _run_koncreet_tasks(tmp_path, digest, *flags):
    payload = tmp_path / "payload"
    payload.write_text("#!/bin/sh\n")
    source = tmp_path / "koncreet.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        archive.add(payload, arcname="koncreet/koncreet")
    (tmp_path / "templates").symlink_to(ROOT / "ansible/templates")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/koncreet.yml")},
                        {
                            "name": "A later task",
                            "ansible.builtin.file": {
                                "path": str(tmp_path / "later"),
                                "state": "touch",
                            },
                        },
                    ],
                }
            ]
        )
    )
    variables = {
        "ansible_become": False,
        "ansible_user_id": "operator",
        "ansible_user_dir": "/home/operator",
        "factory_cfg": {"user": "coder", "profiles": {"tailscale": False}},
        "factory_latest": {"koncreet": {"version": "9.9.9"}},
        "factory_koncreet": {"url": source.as_uri(), "sha256": digest},
        "factory_koncreet_patch": str(ROOT / "patches/koncreet/ubuntu-26.04.patch"),
        "factory_koncreet_prefix": str(tmp_path / "prefix"),
        "factory_koncreet_config": str(tmp_path / "koncreet.conf"),
    }
    # koncreet.yml hands its files to root. Unprivileged, the chown fails before the
    # download is ever checked, so a digest test would pass for the wrong reason.
    # Plan mode (--check) creates nothing and needs no root.
    wrapper = () if os.geteuid() == 0 or "--check" in flags else ("fakeroot",)
    if wrapper and not shutil.which("fakeroot"):
        pytest.skip("koncreet.yml chowns to root: run as root or install fakeroot")
    return _ansible(
        tmp_path,
        "ansible-playbook",
        "-i",
        "localhost,",
        str(playbook),
        "--extra-vars",
        json.dumps(variables),
        *flags,
        wrapper=wrapper,
    )


def test_a_koncreet_tarball_that_fails_its_digest_is_skipped_and_apply_continues(tmp_path):
    result = _run_koncreet_tasks(tmp_path, "0" * 64)
    assert result.returncode == 0, result.stdout
    assert "WARNING: koncreet skipped" in result.stdout
    assert "Fetch the koncreet tarball: The checksum for" in result.stdout
    assert (tmp_path / "later").exists()
    assert not list((tmp_path / "prefix").rglob("patch-outcome"))
    assert not list((tmp_path / "prefix").rglob("*.tar.gz"))
    assert not (tmp_path / "koncreet.conf").exists()


def test_planning_koncreet_installs_nothing_and_warns_of_nothing(tmp_path):
    result = _run_koncreet_tasks(tmp_path, "0" * 64, "--check")
    assert result.returncode == 0, result.stdout
    assert "WARNING" not in result.stdout
    assert not (tmp_path / "prefix").exists()


def test_mac_ssh_keeps_the_existing_key_and_other_host_entries(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    other = "Host build\n  HostName build.example\n"
    (home / ".ssh/config").write_text(other)
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/mac_ssh.yml")}
                    ],
                }
            ]
        )
    )
    variables = {
        "factory_cfg": {
            "user": "coder",
            "home": str(home),
            "mac_ssh": {"host": "mac.example", "user": "operator"},
        },
        "factory_mac_ssh_key": str(home / ".ssh/id_ed25519_mac"),
    }

    def apply():
        result = _ansible(
            tmp_path, "ansible-playbook", "-i", "localhost,", str(playbook),
            "--extra-vars", json.dumps(variables),
        )
        assert result.returncode == 0, result.stdout
        return result.stdout

    first = apply()
    key = (home / ".ssh/id_ed25519_mac").read_bytes()
    public = (home / ".ssh/id_ed25519_mac.pub").read_text().strip()
    config = (home / ".ssh/config").read_text()
    line = (home / ".ssh/id_ed25519_mac.authorized_keys").read_text()
    assert line.startswith('from="') and line.endswith(f'" {public}\n')
    assert public in first and "PRIVATE KEY" not in first
    assert config.endswith(other) and config.splitlines().count("Host mac") == 1
    assert "IdentitiesOnly yes" in config

    second = apply()
    assert "changed=0" in second
    assert (home / ".ssh/id_ed25519_mac").read_bytes() == key
    assert (home / ".ssh/config").read_text() == config
