#!/usr/bin/env python3
"""Report per-home rollups to the Herdr Spaces sidebar (docs/herdr.md).

Run by herdr-spaces.timer every 10 seconds. For every Herdr workspace it finds
the orchestrator home from its panes' directories and reports display-only
workspace tokens under the source `code-factory:spaces`:

  short      short name ("swarms" for "2ndmate-swarms-mate-s4")
  decisions  "⚑ N"  open decisions, from the home's summary ledger, less those of
                    second-level homes that have a live Space of their own
  crew       "▶ N"  live worker task records (state/*.meta, homes excluded)
  queue      "◷ N"  queued tasks ready to start (bin/fm-tasks-axi.sh ready)
  prs        "⎇ N"  open pull requests recorded as pr= in task records
  ci_ok      "✓N"   of those, pull requests whose checks all passed
  ci_bad     "✗N"   of those, pull requests with a failed check
  res        "cpu 29%  ram 2.4G  disk 8.5G"
  alert      "⚠ watcher silent" when the home's supervision is unhealthy

Zero counts are cleared. Disk is cached 15 minutes and pull request state 5
minutes in ~/.cache/code-factory/herdr-spaces.json. A source that fails keeps
its previous value, and the script always exits 0.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SOURCE = "code-factory:spaces"
BLANK = "\u2800"
HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "code-factory"
TOKENS = ("short", "decisions", "crew", "queue", "prs", "ci_ok", "ci_bad", "res", "alert")
DISK_TTL, PR_TTL = 15 * 60, 5 * 60
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def short_name(label: str) -> str:
    """Same mapping as config/herdr-sidebar.ts shortName; "" means none."""
    if "-afk-daemon-" in label:
        return "☾ afk"
    if label.startswith("└"):
        return label.split(" · ")[0]
    if label.startswith("2ndmate-"):
        return re.sub(r"-mate-[^-]+$", "", label[len("2ndmate-") :])
    return label if label == "firstmate" else ""


def run(*args, cwd=None, env=None, timeout=20) -> str:
    return subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def find_home(cwd: str) -> Path | None:
    """The orchestrator home: the git top-level holding state/ and data/."""
    for d in (Path(cwd), *Path(cwd).parents):
        if (d / ".git").exists() and (d / "state").is_dir() and (d / "data").is_dir():
            return d
    return None


def decisions(home: Path, live: set[str], folds: dict) -> int:
    """The summary ledger's open decisions, minus those it folds in from
    second-level homes that have a live Space of their own (they count there).

    Each such home's share is bin/fm-classify-lib.sh's read-only
    status_open_decisions over its status log, cached until that log changes.
    """
    ledger = json.loads((home / "state/home-summary.json").read_text())
    total = int(ledger["counts"]["decisions_open"])
    for meta in (home / "state").glob("*.meta"):
        fields = dict(line.split("=", 1) for line in meta.read_text().splitlines() if "=" in line)
        if fields.get("kind") != "secondmate" or fields.get("herdr_workspace_id") not in live:
            continue
        log = meta.with_suffix(".status")
        if not log.exists():
            continue
        stamp = [log.stat().st_mtime_ns, log.stat().st_size]
        hit = folds.get(str(log))
        if not hit or hit["stamp"] != stamp:
            script = '. "$1" && o=$(status_open_decisions "$2") && printf %s "$o" | awk "NF{n++} END{print n+0}"'
            lib = home / "bin/fm-classify-lib.sh"
            out = run("bash", "-c", script, "_", lib, log, timeout=60)
            hit = folds[str(log)] = {"stamp": stamp, "n": int(out.strip() or 0)}
        total -= hit["n"]
    return max(total, 0)


def crew(home: Path) -> int:
    metas = (m.read_text() for m in (home / "state").glob("*.meta"))
    return sum("\nkind=secondmate\n" not in f"\n{text}\n" for text in metas)


def queue(home: Path) -> int:
    env = {**os.environ, "FM_HOME": str(home)}
    out = run(home / "bin/fm-tasks-axi.sh", "ready", cwd=home, env=env)
    return int(re.search(r"^count: (\d+)", out, re.M)[1])


def watcher_silent(home: Path) -> bool:
    """bin/fm-supervision-lib.sh's verdict: work needs a watcher, none is beating."""
    lib = home / "bin/fm-supervision-lib.sh"
    if not lib.is_file():
        raise FileNotFoundError(lib)
    script = '. "$1" && fm_supervision_unhealthy "$2"'
    rc = subprocess.run(["bash", "-c", script, "_", lib, home / "state"], timeout=20).returncode
    return rc == 0


def pr_urls(home: Path) -> set[str]:
    return {
        line[3:].strip()
        for meta in (home / "state").glob("*.meta")
        for line in meta.read_text().splitlines()
        if line.startswith("pr=")
    }


def ci_state(url: str) -> str:
    """ "closed", "ok", "bad" or "pending" for one pull request URL, via REST."""
    owner, repo, _, number = url.rstrip("/").split("/")[-4:]
    pull = json.loads(run("gh", "api", f"repos/{owner}/{repo}/pulls/{number}"))
    if pull["state"] != "open":
        return "closed"
    runs = json.loads(
        run(
            "gh",
            "api",
            f"repos/{owner}/{repo}/commits/{pull['head']['sha']}/check-runs?per_page=100",
        )
    )["check_runs"]
    conclusions = {r["conclusion"] for r in runs}
    if conclusions & {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}:
        return "bad"
    if runs and conclusions <= {"success", "skipped", "neutral"}:
        return "ok"
    return "pending"


def disk_paths(home: Path, other_homes: set[Path]) -> list[Path]:
    """The home plus its projects' worktree pools, as treehouse reports them."""
    paths = [home]
    for project in sorted((home / "projects").glob("*/")):
        try:
            pool = json.loads(run("treehouse", "status", "--json", cwd=project))
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        paths += [Path(w["path"]) for w in pool if Path(w["path"]) not in other_homes]
    return paths


def disk_bytes(paths: list[Path]) -> int:
    out = subprocess.run(
        ["du", "-sxbc", "--", *map(str, paths)],
        capture_output=True,
        text=True,
        timeout=300,
    ).stdout
    return int(out.splitlines()[-1].split()[0])


def processes() -> dict[str, list[tuple[int, int, int]]]:
    """(pid, cpu ticks, rss bytes) per HERDR_WORKSPACE_ID, for readable processes."""
    found: dict[str, list[tuple[int, int, int]]] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            env = (proc / "environ").read_bytes()
            m = re.search(rb"(?:^|\0)HERDR_WORKSPACE_ID=([^\0]*)", env)
            if not m:
                continue
            stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            rss = int((proc / "statm").read_text().split()[1]) * PAGE
        except OSError:
            continue
        ticks = int(stat[11]) + int(stat[12])
        found.setdefault(m[1].decode(), []).append((int(proc.name), ticks, rss))
    return found


def gib(n: float) -> str:
    return f"{n / 2**30:.1f}G"


def count(n: int, glyph: str) -> str:
    return f"{glyph}{n}" if n else ""


def main() -> None:
    cache_file = CACHE / "herdr-spaces.json"
    try:
        cache = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cache = {}
    last = cache.setdefault("tokens", {})
    now = time.time()

    workspaces = json.loads(run(HERDR, "workspace", "list"))["result"]["workspaces"]
    panes = json.loads(run(HERDR, "pane", "list"))["result"]["panes"]
    homes: dict[str, Path] = {}
    for pane in panes:
        home = find_home(pane.get("cwd") or "/")
        if home and pane["workspace_id"] not in homes:
            homes[pane["workspace_id"]] = home

    procs = processes()
    prev_cpu = cache.get("cpu", {})
    dt = now - cache.get("cpu_at", now)
    pr_cache, disk_cache = cache.get("pr", {}), cache.setdefault("disk", {})
    folds = cache.get("folds", {})
    live_ids = {ws["workspace_id"] for ws in workspaces}
    seen_prs: dict[str, dict] = {}

    def save() -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(cache_file)

    def pr_counts(home: Path) -> list[str]:
        states = []
        for url in sorted(pr_urls(home)):
            hit = pr_cache.get(url)
            if not hit or now - hit["at"] >= PR_TTL:
                hit = {"at": now, "state": ci_state(url)}
            seen_prs[url] = pr_cache[url] = hit
            states.append(hit["state"])
        live = [s for s in states if s != "closed"]
        return [count(len(live), "⎇ "), count(live.count("ok"), "✓"), count(live.count("bad"), "✗")]

    def res(wid: str, home: Path | None) -> list[str]:
        rows = procs.get(wid, [])
        parts = []
        before = prev_cpu.get(wid)
        if before is not None and dt > 0:
            used = sum(t - before[str(p)] for p, t, _ in rows if str(p) in before)
            parts.append(f"cpu {used / TICK / dt / os.cpu_count() * 100:.0f}%")
        parts.append(f"ram {gib(sum(r for _, _, r in rows))}")
        if home:
            hit = disk_cache.get(str(home))
            if not hit or now - hit["at"] >= DISK_TTL:
                others = set(homes.values()) - {home}
                try:
                    size = disk_bytes(disk_paths(home, others))
                except (OSError, subprocess.SubprocessError, ValueError, IndexError) as err:
                    print(f"{home}: disk: {err}", file=sys.stderr)
                    size = hit and hit["bytes"]
                hit = disk_cache[str(home)] = {"at": now, "bytes": size}
                save()
            if hit["bytes"] is not None:
                parts.append(f"disk {gib(hit['bytes'])}")
        return [BLANK * 2 + "  ".join(parts)]

    for ws in workspaces:
        wid, label = ws["workspace_id"], ws.get("label", "")
        # Helper and per-task spaces get their short name only.
        helper = "-afk-daemon-" in label or label.startswith("└")
        home = None if helper else homes.get(wid)
        keep = last.get(wid, {})
        values: dict[str, str | None] = dict.fromkeys(TOKENS, "")
        values["short"] = short_name(label)

        def fill(keys, compute):
            """A source that fails keeps its previous value; unknown ones stay untouched."""
            try:
                values.update(zip(keys, compute()))
            except Exception as err:  # noqa: BLE001 - display-only, never fatal
                print(f"{label}: {keys[0]}: {err}", file=sys.stderr)
                values.update({k: keep.get(k) for k in keys})

        if home:
            fill(["decisions"], lambda: [count(decisions(home, live_ids, folds), "⚑ ")])
            fill(["crew"], lambda: [count(crew(home), "▶ ")])
            fill(["queue"], lambda: [count(queue(home), "◷ ")])
            fill(["prs", "ci_ok", "ci_bad"], lambda: pr_counts(home))
            silent = BLANK * 2 + "⚠ watcher silent"
            fill(["alert"], lambda: [silent if watcher_silent(home) else ""])
        if not helper:
            fill(["res"], lambda: res(wid, home))

        args = [HERDR, "workspace", "report-metadata", wid, "--source", SOURCE]
        for key, value in values.items():
            if value is not None:
                args += ["--token", f"{key}={value}"] if value else ["--clear-token", key]
        try:
            run(*args)
            last[wid] = values
        except (OSError, subprocess.SubprocessError) as err:
            print(f"{label}: report: {err}", file=sys.stderr)

    cache.update(
        tokens={k: v for k, v in last.items() if k in live_ids},
        cpu={w: {str(pid): t for pid, t, _ in procs.get(w, [])} for w in live_ids},
        cpu_at=now,
        pr=seen_prs,
        folds=folds,
    )
    save()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 - a timer run must never fail loudly
        print(f"herdr-spaces: {err}", file=sys.stderr)
