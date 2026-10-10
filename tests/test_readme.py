import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas/factory.schema.json").read_text())
DEFAULT = yaml.safe_load((ROOT / "config/default.yml").read_text())
SPEC = importlib.util.spec_from_file_location("provisions", ROOT / "scripts/provisions.py")
provisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisions)

# Host config switch -> the doc its Features line links.
FEATURES = {
    "factory.profiles.agents": "docs/omp.md",
    "factory.profiles.chat": "docs/chat.md",
    "factory.profiles.tailscale": "docs/security.md#remote-access",
    "factory.profiles.desktop": "docs/recovery.md#desktop-access",
    "factory.profiles.fleet_guards": "docs/fleet-guards.md",
    "factory.profiles.fleet_browsers": "docs/fleet-guards.md#browser-ladder",
    "factory.data_dir": "docs/configuration.md#data-disk",
    "factory.firstmate.checklist": "docs/configuration.md#new-host-questions",
    "factory.mac_ssh": "docs/security.md#ssh-to-a-mac",
    "factory.imessage": "docs/imessage.md",
    "factory.github_board": "docs/github-board.md",
    "factory.ci_pool": "docs/ci-pool.md",
}
EXCLUDED = {
    # Base installs, listed under "Profiles on" in Default config.
    "factory.profiles.development",
    "factory.profiles.firstmate",
    "factory.profiles.docker",
    # Settings of a feature that another switch turns on.
    "factory.docker",
    "factory.fleet",
    "factory.fleet.docker_guard",
    "factory.browsers",
}


def switches(node=SCHEMA, path=()):
    """Every profile, optional `factory` key and optional block: path -> off by default."""
    for key, sub in node.get("properties", {}).items():
        here = path + (key,)
        optional = key not in node.get("required", ())
        if (
            path[-1:] == ("profiles",)
            or optional
            and (len(here) == 2 or sub.get("type") == "object")
        ):
            value = DEFAULT
            for part in here:
                value = value.get(part) if isinstance(value, dict) else None
            yield ".".join(here), value in (None, False, "")
        yield from switches(sub, here)


def section(summary):
    text = (ROOT / "README.md").read_text()
    body = text.split(f"<summary><b>{summary}</b></summary>", 1)[1].split("</details>", 1)[0]
    return [line for line in body.splitlines() if line.startswith("- ")]


def ticks(names):
    return ", ".join(f"`{name}`" for name in names)


def test_every_config_switch_has_a_features_line_tagged_opt_in_when_off_by_default():
    found = dict(switches())
    assert set(found) == FEATURES.keys() | EXCLUDED, "map the new switch in FEATURES or EXCLUDED"
    lines = section("Features")
    for path, link in FEATURES.items():
        assert (ROOT / link.split("#")[0]).is_file(), link
        matches = [line for line in lines if f"]({link})" in line]
        assert len(matches) == 1, f"{path}: one Features line must link {link}"
        assert matches[0].endswith(" (opt-in)") == found[path], matches[0]


def test_default_config_lists_the_current_defaults():
    omp = yaml.safe_load((ROOT / "config/omp.yml").read_text())
    roles = omp["modelRoles"]
    group_vars = yaml.safe_load((ROOT / "ansible/group_vars/all.yml").read_text())
    extensions = {
        Path(value).stem
        for value in group_vars.values()
        if isinstance(value, str) and "/.omp/agent/extensions/" in value
    }
    patches = {path.stem for path in (ROOT / "patches/firstmate").glob("*.patch")}
    profiles = DEFAULT["factory"]["profiles"]
    unset = [
        path.removeprefix("factory.")
        for path, off in switches()
        if off and ".profiles." not in path
    ]
    lines = section("Default config")
    for line in [
        f"- Agent harness: [omp](docs/omp.md), default model `{roles['default']}`, "
        f"advisor {'on' if omp['advisor']['enabled'] else 'off'}",
        "- Models: " + ticks(sorted({model.split(":")[0] for model in roles.values()})),
        "- omp plugins: " + ticks(provisions.OMP_PLUGINS),
        "- Profiles on: " + ticks(name for name, on in profiles.items() if on),
        "- Profiles off (opt-in): " + ticks(name for name, on in profiles.items() if not on),
        "- Unset (opt-in): " + ticks(unset),
    ]:
        assert line in lines

    def named(prefix):
        return {line.split("`")[1] for line in lines if line.startswith(prefix)}

    assert named("- omp extension `") == extensions
    assert named("- Firstmate patch `") == patches
