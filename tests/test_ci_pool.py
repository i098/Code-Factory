import importlib.util
import io
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pool_script = load("ci_pool", "maintenance/ci-pool.py")
factory = load("factory_config_ci_pool", "scripts/factory.py")

POOL = {"job_cpus": 4, "job_memory_gb": 8}


def test_auto_size_takes_half_the_spare_cpu_or_memory_whichever_is_tighter():
    # 96 CPUs at load 8: 44 spare CPUs / 4 per job = 11; 199 GiB / 2 / 8 = 12.
    assert pool_script.auto_slots(POOL, 96, 8.0, 199.0) == 11
    # Memory binds: 40 GiB / 2 / 8 = 2.5.
    assert pool_script.auto_slots(POOL, 96, 8.0, 40.0) == 2
    # A host loaded past its CPU count has no spare CPU.
    assert pool_script.auto_slots(POOL, 8, 12.0, 199.0) == 0


def test_slots_past_the_pool_total_are_dropped_from_the_end_of_the_list(capsys):
    pool = {"repos": [{"repo": "o/First", "slots": 2}, {"repo": "o/second.repo", "slots": 2}]}
    assert pool_script.wanted_slots(pool, 3) == ["o-first-1", "o-first-2", "o-second-repo-1"]
    assert "o-second-repo-2" in capsys.readouterr().err
    assert pool_script.wanted_slots(pool, 10) == [
        "o-first-1", "o-first-2", "o-second-repo-1", "o-second-repo-2"
    ]


def test_check_lists_removed_slots_and_their_directories_without_touching_them(
    tmp_path, monkeypatch, capsys
):
    units = tmp_path / "units"
    wants = units / "default.target.wants"
    wants.mkdir(parents=True)
    (units / "ci-runner@.service").write_text(pool_script.UNIT_TEXT)
    for name in ("o-kept-1", "o-gone-1"):
        (wants / f"ci-runner@{name}.service").touch()
    data = tmp_path / "data"
    for path in ("work/o-kept-1", "work/o-gone-1", "cache/o-kept", "cache/o-gone"):
        (data / path).mkdir(parents=True)
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "TEMPLATE", units / "ci-runner@.service")
    monkeypatch.setattr(pool_script, "WANTS", wants)
    config = {"data_dir": str(data), "total_slots": 5,
              "repos": [{"repo": "o/kept", "slots": 2, "labels": ["x"]}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(config)))

    assert pool_script.apply(check=True) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"write {tmp_path / 'pool.json'}",
        "stop ci-runner@o-gone-1.service",
        f"remove {data / 'work/o-gone-1'}",
        f"remove {data / 'cache/o-gone'}",
        "start ci-runner@o-kept-2.service",
    ]
    assert not (tmp_path / "pool.json").exists()
    assert (wants / "ci-runner@o-gone-1.service").exists()
    assert (data / "work/o-gone-1").is_dir()


@pytest.fixture
def configuration():
    document = yaml.safe_load((ROOT / "config/default.yml").read_text())
    document["factory"]["ci_pool"] = {
        "data_dir": "/srv/ci",
        "repos": [{"repo": "o/repo", "slots": 2, "labels": ["pool"]}],
    }
    return document


def test_two_repositories_that_share_a_unit_name_are_rejected(configuration):
    configuration["factory"]["ci_pool"]["repos"].append(
        {"repo": "O/Repo", "slots": 1, "labels": ["pool"]}
    )
    with pytest.raises(ValueError, match="twice"):
        factory.validate_config(configuration)


def test_pool_requires_the_docker_profile(configuration):
    configuration["factory"]["profiles"]["docker"] = False
    configuration["factory"]["profiles"]["fleet_guards"] = False
    with pytest.raises(ValueError, match="docker profile"):
        factory.validate_config(configuration)
