import grp
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def merge_models(home, check=False):
    playbook = home / "merge.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars": {
            "ansible_become": False,
            "code_factory_repo": str(ROOT),
            "factory_cfg": {"home": str(home), "user": pwd.getpwuid(os.getuid()).pw_name},
            "factory_group": grp.getgrgid(os.getgid()).gr_name,
        },
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/omp_models.yml")}],
    }]))
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
         str(playbook), *(["--check"] if check else [])],
        cwd=home, env={**os.environ, "HOME": str(home)}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


@pytest.mark.parametrize("existing", [False, True])
def test_model_merge_keeps_user_entries_and_is_idempotent(tmp_path, existing):
    target = tmp_path / ".omp/agent/models.yml"
    target.parent.mkdir(parents=True)
    custom = {"providers": {
        "private-provider": {"baseUrl": "https://example.com", "models": [{"id": "local"}]},
        "openai-codex": {
            "models": [{"id": "user-model"}],
            "modelOverrides": {
                "user-model": {"contextWindow": 64000},
                "gpt-6.1-sol": {"contextWindow": 64000, "maxTokens": 8192},
            },
        },
    }}
    if existing:
        target.write_text(yaml.safe_dump(custom))
    before = target.read_bytes() if existing else None
    assert merge_models(tmp_path, check=True) == 1
    assert (target.read_bytes() if target.exists() else None) == before
    assert merge_models(tmp_path) == 1
    merged = yaml.safe_load(target.read_text())
    shipped = yaml.safe_load((ROOT / "config/omp-models.yml").read_text())
    overrides = merged["providers"]["openai-codex"]["modelOverrides"]
    for model, values in shipped["providers"]["openai-codex"]["modelOverrides"].items():
        assert overrides[model].items() >= values.items()
    if existing:
        assert merged["providers"]["private-provider"] == custom["providers"]["private-provider"]
        assert merged["providers"]["openai-codex"]["models"] == [{"id": "user-model"}]
        assert overrides["user-model"] == {"contextWindow": 64000}
        assert overrides["gpt-6.1-sol"]["maxTokens"] == 8192
    assert target.stat().st_mode & 0o777 == 0o600
    written = target.read_bytes()
    assert merge_models(tmp_path) == 0
    assert target.read_bytes() == written


def test_shipped_model_configuration_schema():
    from jsonschema import validate

    window = {"type": "integer", "minimum": 1}
    validate(yaml.safe_load((ROOT / "config/omp-models.yml").read_text()), {
        "type": "object", "required": ["providers"], "additionalProperties": False,
        "properties": {"providers": {
            "type": "object", "required": ["openai-codex"], "additionalProperties": False,
            "properties": {"openai-codex": {
                "type": "object", "required": ["modelOverrides"], "additionalProperties": False,
                "properties": {"modelOverrides": {
                    "type": "object", "minProperties": 1,
                    "additionalProperties": {
                        "type": "object", "required": ["contextWindow", "maxContextWindow"],
                        "additionalProperties": False,
                        "properties": {"contextWindow": window, "maxContextWindow": window},
                    },
                }},
            }},
        }},
    })
    dispatch = json.loads((ROOT / "config/crew-dispatch.json").read_text())
    for tier in [dispatch["default"], *(rule["use"] for rule in dispatch["rules"])]:
        assert isinstance(tier, list)
        for model in tier:
            assert set(model) == {"harness", "model", "provider"}
            assert model["harness"] == "omp"
            assert model["provider"] in {"claude", "codex"}
