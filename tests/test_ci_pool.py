import importlib.util
import io
import json
import shutil
import subprocess
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


def test_busy_slots_do_not_shrink_the_auto_size():
    # 6 busy slots hold 24 CPUs and 48 GiB of the load: the size is the idle host's.
    loaded = pool_script.auto_slots(POOL, 96, 8.0 + 24, 199.0 - 48, 6)
    assert loaded == pool_script.auto_slots(POOL, 96, 8.0, 199.0)
    assert pool_script.auto_slots(POOL, 96, 8.0 + 24, 199.0 - 48) < loaded


def test_slots_past_the_pool_total_are_dropped_from_the_end_of_the_list(capsys):
    pool = {"repos": [{"repo": "o/First", "slots": 2}, {"repo": "o/second.repo", "slots": 2}]}
    assert pool_script.wanted_slots(pool, 3) == ["o-first-1", "o-first-2", "o-second-repo-1"]
    assert "o-second-repo-2" in capsys.readouterr().err
    assert pool_script.wanted_slots(pool, 10) == [
        "o-first-1", "o-first-2", "o-second-repo-1", "o-second-repo-2"
    ]


@pytest.fixture
def slots(tmp_path, monkeypatch):
    """Pool state: kept-1 and gone-1 enabled, work/cache dirs for both, a foreign dir."""
    units = tmp_path / "units"
    wants = units / "default.target.wants"
    wants.mkdir(parents=True)
    (units / "ci-runner@.service").write_text(pool_script.UNIT_TEXT)
    for name in ("o-kept-1", "o-gone-1"):
        (wants / f"ci-runner@{name}.service").touch()
    data = tmp_path / "data"
    for path in ("ci-pool/work/o-kept-1", "ci-pool/work/o-gone-1", "ci-pool/cache/o-kept",
                 "ci-pool/cache/o-gone", "work/projects", "cache/models"):
        (data / path).mkdir(parents=True)
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "TEMPLATE", units / "ci-runner@.service")
    monkeypatch.setattr(pool_script, "WANTS", wants)
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "remove_tree", shutil.rmtree)
    calls = []
    monkeypatch.setattr(pool_script, "systemctl", lambda *args: calls.append(args))

    def apply(check=False, **overrides):
        config = {"data_dir": str(data), "total_slots": 5,
                  "repos": [{"repo": "o/kept", "slots": 2, "labels": ["x"]}], **overrides}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(config)))
        return pool_script.apply(check=check)

    return data, calls, apply


def test_check_lists_removed_slots_and_their_directories_without_touching_them(
    slots, tmp_path, capsys
):
    data, calls, apply = slots

    assert apply(check=True) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"write {tmp_path / 'pool.json'}",
        "stop ci-runner@o-gone-1.service",
        f"remove {data / 'ci-pool/work/o-gone-1'}",
        f"remove {data / 'ci-pool/cache/o-gone'}",
        "start ci-runner@o-kept-2.service",
    ]
    assert not (tmp_path / "pool.json").exists()
    assert (data / "ci-pool/work/o-gone-1").is_dir()
    assert calls == []


def test_apply_deletes_only_what_the_pool_created(slots):
    data, calls, apply = slots

    assert apply() == 0

    assert not (data / "ci-pool/work/o-gone-1").exists()
    assert not (data / "ci-pool/cache/o-gone").exists()
    assert (data / "ci-pool/work/o-kept-1").is_dir()
    assert (data / "work/projects").is_dir()
    assert (data / "cache/models").is_dir()
    assert ("disable", "--now", "ci-runner@o-gone-1.service") in calls


def test_shrinking_stops_idle_slots_but_only_drains_busy_ones(slots, monkeypatch, capsys):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-kept-2")
    (data / "ci-pool/work/o-kept-2").mkdir()
    (pool_script.WANTS / "ci-runner@o-kept-2.service").touch()

    assert apply(total_slots=1) == 0

    assert ("disable", "ci-runner@o-kept-2.service") in calls
    assert ("disable", "--now", "ci-runner@o-kept-2.service") not in calls
    assert ("disable", "--now", "ci-runner@o-gone-1.service") in calls
    assert (data / "ci-pool/work/o-kept-2").is_dir()
    assert (data / "ci-pool/cache/o-kept").is_dir()
    assert not (data / "ci-pool/work/o-gone-1").exists()
    assert "drain ci-runner@o-kept-2.service" in capsys.readouterr().out


def test_a_drained_slot_keeps_its_repository_cache_while_it_is_busy(slots, monkeypatch):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-gone-1")

    assert apply(repos=[]) == 0

    assert (data / "ci-pool/work/o-gone-1").is_dir()
    assert (data / "ci-pool/cache/o-gone").is_dir()
    assert not (data / "ci-pool/work/o-kept-1").exists()
    assert not (data / "ci-pool/cache/o-kept").exists()


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


def test_failed_container_create_deletes_the_runner_and_pauses(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"), "job_cpus": 4, "job_memory_gb": 8,
        "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    sleeps, calls = [], []
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    def fake_run(argv, **kwargs):
        if argv[0] == "gh":
            out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
            return subprocess.CompletedProcess(argv, 0, out, "")
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)

    assert pool_script.run("o-kept-1") == 1
    assert sleeps == [pool_script.FAILURE_PAUSE_SECONDS]
    assert any(argv[:3] == ["gh", "api", "--method"] and argv[3] == "DELETE" for argv in calls)
