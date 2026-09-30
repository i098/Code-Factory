#!/usr/bin/env python3
"""Report per-home rollups to the Herdr Spaces sidebar (docs/herdr.md).

Run by herdr-spaces.timer every 10 seconds. For every Herdr workspace it finds
the orchestrator home from its panes' directories and reports display-only
workspace tokens under the source `code-factory:spaces`:

  short      short name ("swarms" for "2ndmate-swarms-mate-s4")
  decisions  "⚑ N"  fresh open decisions (parked captain-hold-* keys left out):
                    a second-level home's own, or the primary home's own workers'
  crew       "▶ N"  live worker task records (state/*.meta, homes excluded)
  queue      "◷ N"  queued tasks ready to start (bin/fm-tasks-axi.sh ready)
  res        "⚙ 29%  ▤ 8%  ⛁ 2%"  CPU, RAM and disk, as shares of the machine
  alert      "⚠ watcher silent" when the home's supervision is unhealthy
  host       "⌂ ⚙ 41%  ▤ 18.2/31.0G 59%  ⛁ 402/937G 43%"  the whole machine,
             on the primary home only (labelled firstmate, else the first listed),
             whose res and alert are indented two columns to sit under its name

Zero counts are cleared. Disk is cached 15 minutes in
~/.cache/code-factory/herdr-spaces.json. A source that fails keeps
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
HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "code-factory"
TOKENS = ("short", "decisions", "crew", "queue", "res", "alert", "host")
DISK_TTL = 15 * 60
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
BLANK = "\u2800"


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


def open_keys(home: Path, log: Path, folds: dict) -> int:
    """Fresh open decisions in one status log: bin/fm-classify-lib.sh's read-only
    status_open_decisions, minus parked captain holds (keys captain-hold-*).
    Cached until the log changes."""
    stamp = [log.stat().st_mtime_ns, log.stat().st_size]
    hit = folds.get(str(log))
    if not hit or hit["stamp"] != stamp or "fresh" not in hit:
        script = '. "$1" && status_open_decisions "$2"'
        out = run("bash", "-c", script, "_", home / "bin/fm-classify-lib.sh", log, timeout=60)
        keys = [line.split("\t", 1)[0] for line in out.splitlines() if line.strip()]
        hit = folds[str(log)] = {
            "stamp": stamp,
            "fresh": sum(not k.startswith("captain-hold-") for k in keys),
        }
    return hit["fresh"]


def decisions(primary: Path, wid: str, is_primary: bool, folds: dict) -> int:
    """Decisions waiting on the operator, counted where they can be acted on.

    Every count comes from the primary home's status logs. A second-level home's
    Space shows the fresh escalations in its own log (state/<mate>.status, the meta
    whose herdr_workspace_id is this Space). The primary Space shows only its own
    workers' logs. Parked holds never count, and a second-level home with no live
    Space (closed or not running) is not shown anywhere.
    """
    total = 0
    for meta in (primary / "state").glob("*.meta"):
        fields = dict(line.split("=", 1) for line in meta.read_text().splitlines() if "=" in line)
        mate = fields.get("kind") == "secondmate"
        if (mate and fields.get("herdr_workspace_id") != wid) or (not mate and not is_primary):
            continue
        log = meta.with_suffix(".status")
        if log.exists():
            total += open_keys(primary, log, folds)
    return total


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
    """(pid, own cpu ticks, rss bytes) per HERDR_WORKSPACE_ID, for readable processes."""
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


def meminfo() -> tuple[int, int]:
    """(MemTotal, MemAvailable) in bytes."""
    lines = Path("/proc/meminfo").read_text().splitlines()
    info = dict(line.split(":", 1) for line in lines)
    return int(info["MemTotal"].split()[0]) * 1024, int(info["MemAvailable"].split()[0]) * 1024


def cpu_times() -> list[int]:
    """[busy, total] jiffies of the whole machine, from /proc/stat."""
    fields = [int(f) for f in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:9]]
    return [sum(fields) - fields[3] - fields[4], sum(fields)]


def fs_size(path: Path | str) -> int:
    st = os.statvfs(path)
    return st.f_blocks * st.f_frsize


def pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.0f}%"


def used_of(used: float, total: float, fine: bool = False) -> str:
    """ "402/937G", "1.4/1.9T", "12/20T": whole G below 1000G, then T with one
    decimal below 10T; `fine` keeps one decimal below 100G ("18.2/31.0G")."""
    size, unit = (2**30, "G") if total < 999.5 * 2**30 else (2**40, "T")
    if unit == "G":
        digits = 1 if fine and total < 99.95 * size else 0
    else:
        digits = 1 if total < 9.95 * size else 0
    return f"{used / size:.{digits}f}/{total / size:.{digits}f}{unit}"


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
    disk_cache = cache.setdefault("disk", {})
    folds = cache.get("folds", {})
    live_ids = {ws["workspace_id"] for ws in workspaces}

    def save() -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(cache_file)

    def res(wid: str, home: Path | None) -> str:
        rows = procs.get(wid, [])
        parts = []
        before = prev_cpu.get(wid)
        if before is not None and dt > 0:
            used = sum(t - before[str(p)] for p, t, _ in rows if str(p) in before)
            cores = os.cpu_count()
            parts.append(f"⚙ {pct(min(max(used / TICK / dt, 0), cores), cores)}")
        parts.append(f"▤ {pct(sum(r for _, _, r in rows), meminfo()[0])}")
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
                parts.append(f"⛁ {pct(hit['bytes'], fs_size(home))}")
        return "  ".join(parts)

    def host() -> list[str]:
        busy, total = cpu_times()
        before = cache.get("host_cpu")
        cache["host_cpu"] = [busy, total]
        parts = []
        if before and total > before[1]:
            parts.append(f"⚙ {pct(busy - before[0], total - before[1])}")
        mem_total, mem_free = meminfo()
        mem_used = mem_total - mem_free
        parts.append(f"▤ {used_of(mem_used, mem_total, fine=True)} {pct(mem_used, mem_total)}")
        st = os.statvfs("/")
        disk_total, disk_used = st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bfree) * st.f_frsize
        parts.append(f"⛁ {used_of(disk_used, disk_total)} {pct(disk_used, disk_total)}")
        return ["⌂ " + "  ".join(parts)]

    first = workspaces[0] if workspaces else {}
    primary = next((ws for ws in workspaces if ws.get("label") == "firstmate"), first)

    for ws in workspaces:
        wid, label = ws["workspace_id"], ws.get("label", "")
        # Helper and per-task spaces get their short name only.
        helper = "-afk-daemon-" in label or label.startswith("└")
        home = None if helper else homes.get(wid)
        pad = BLANK * 2 if wid == primary.get("workspace_id") else ""
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
            primary_home = homes.get(primary.get("workspace_id"))
            if primary_home:
                fill(
                    ["decisions"],
                    lambda: [
                        count(
                            decisions(primary_home, wid, wid == primary.get("workspace_id"), folds),
                            "⚑ ",
                        )
                    ],
                )
            fill(["crew"], lambda: [count(crew(home), "▶ ")])
            fill(["queue"], lambda: [count(queue(home), "◷ ")])
            silent = "⚠ watcher silent"
            fill(["alert"], lambda: [pad + silent if watcher_silent(home) else ""])
        if not helper:
            fill(["res"], lambda: [pad + res(wid, home)])
        if wid == primary.get("workspace_id"):
            fill(["host"], host)

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
        folds=folds,
    )
    save()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 - a timer run must never fail loudly
        print(f"herdr-spaces: {err}", file=sys.stderr)
