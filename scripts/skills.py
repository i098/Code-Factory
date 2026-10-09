#!/usr/bin/env python3
"""Install the repository's skills for omp and Claude Code.

skills/public/<name>/ ships with Crewship; skills/private/<name>/ stays on the
host and wins over a public skill of the same name. Each skill is copied into
every root in ROOTS. A manifest records the names this script installed, so a
skill the operator put there by hand is never replaced or removed. stdout is
one JSON result.
"""

import argparse
import json
import shutil
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
ROOTS = (".omp/agent/skills", ".claude/skills")
MANIFEST = ".local/share/code-factory/skills.json"


def sources(skills):
    found = {}
    for kind in ("public", "private"):  # private last, so it wins a name clash
        for skill in sorted((skills / kind).glob("*/SKILL.md")):
            found[skill.parent.name] = skill.parent
    return found


def tree(path):
    if not path.is_dir():
        return None
    return {
        p.relative_to(path).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o111)
        for p in path.rglob("*")
        if p.is_file()
    }


def install(home, skills=SKILLS):
    record = home / MANIFEST
    owned = json.loads(record.read_text()) if record.is_file() else {}
    wanted = sources(skills)
    changed, skipped = False, []
    for root in ROOTS:
        mine = set(owned.get(root, []))
        for name, source in wanted.items():
            target = home / root / name
            if name not in mine and (target.exists() or target.is_symlink()):
                skipped.append(str(target))
                continue
            if tree(target) != tree(source):
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(source, target)
                changed = True
            mine.add(name)
        for name in mine - wanted.keys():
            shutil.rmtree(home / root / name, ignore_errors=True)
            changed = True
        owned[root] = sorted(mine & wanted.keys())
    text = json.dumps(owned, sort_keys=True) + "\n"
    if not record.is_file() or record.read_text() != text:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(text)
    return {"changed": changed, "installed": sorted(wanted), "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    print(json.dumps(install(parser.parse_args().home.resolve(strict=True))))
