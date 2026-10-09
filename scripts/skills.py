#!/usr/bin/env python3
"""Install the repository's skills for omp and Claude Code.

skills/public/<name>/ ships with Crewship; skills/private/<name>/ stays on the
host and wins over a public skill of the same name. With --private-source (a
local directory, or a git URL fetched at --private-ref, default HEAD), the
skills found there are first copied into skills/private/. Each skill is then
copied into every root in ROOTS. A manifest records the names this script
installed, so a skill the operator put there by hand is never replaced or
removed. stdout is one JSON result.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
ROOTS = (".omp/agent/skills", ".claude/skills")
PRIVATE = "skills/private"  # manifest key for the skills filled from --private-source
MANIFEST = ".local/share/code-factory/skills.json"
CACHE = ".cache/code-factory/private-skills"


def found(directory):
    return {p.parent.name: p.parent for p in sorted(directory.glob("*/SKILL.md"))}


def sources(skills):
    return {**found(skills / "public"), **found(skills / "private")}  # private wins


def fetch(source, ref, cache):
    """Return the directory that holds the private skills; a git URL is fetched into cache."""
    if source.startswith("/"):
        if not Path(source).is_dir():  # a missing source must never read as "no skills"
            raise FileNotFoundError(source)
        return Path(source)
    # Credentials come from the account's own git and GitHub sign-in; never prompt.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if not (cache / ".git").is_dir():
        subprocess.run(["git", "init", "-q", str(cache)], check=True, env=env)
    for step in (["fetch", "-q", "--depth", "1", source, ref], ["checkout", "-qf", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", str(cache), *step], check=True, env=env)
    return cache


def tree(path):
    if not path.is_dir():
        return None
    return {
        p.relative_to(path).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o111)
        for p in path.rglob("*")
        if p.is_file()
    }


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def sync(wanted, base, mine, skipped):
    """Copy each wanted skill into base and remove the ones in mine that are no longer wanted."""
    changed = False
    for name, source in wanted.items():
        target = base / name
        if name not in mine and (target.exists() or target.is_symlink()):
            skipped.append(str(target))
            continue
        mine.add(name)  # claimed before the copy, so a failed copy is retried
        if tree(target) != tree(source):
            remove(target)
            shutil.copytree(source, target)
            changed = True
    for name in mine - wanted.keys():
        remove(base / name)
        mine.discard(name)
        changed = True
    return changed


def install(home, skills=SKILLS, private_source=None, private_ref="HEAD"):
    record = home / MANIFEST
    owned = json.loads(record.read_text()) if record.is_file() else {}
    owned = {key: set(owned.get(key, [])) for key in (PRIVATE, *ROOTS)}
    before = json.dumps({r: sorted(n) for r, n in owned.items()}, sort_keys=True) + "\n"
    changed, skipped = False, []
    try:
        if private_source:
            filled = found(fetch(private_source, private_ref, home / CACHE))
            changed |= sync(filled, skills / "private", owned[PRIVATE], skipped)
        wanted = sources(skills)
        for root in ROOTS:
            changed |= sync(wanted, home / root, owned[root], skipped)
    finally:
        text = json.dumps({r: sorted(n) for r, n in owned.items()}, sort_keys=True) + "\n"
        if text != before:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(text)
    return {"changed": changed, "installed": sorted(wanted), "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--private-source")
    parser.add_argument("--private-ref", default="HEAD")
    args = parser.parse_args()
    home = args.home.resolve(strict=True)
    print(json.dumps(install(home, SKILLS, args.private_source, args.private_ref)))
