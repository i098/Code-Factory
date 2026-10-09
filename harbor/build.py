"""Builds harbor/dist from harbor/public and fills the points of interest from the repository.

The features come from the README's Docs table, the release from CHANGELOG.md, so the page
follows Crewship as it changes. Standard library only: python3 harbor/build.py
"""

import html
import re
import shutil
import sys
from pathlib import Path

HARBOR = Path(__file__).resolve().parent
ROOT = HARBOR.parent
REPO = "https://github.com/i098/Crewship"
MARK = "<!-- points: harbor/build.py fills this list from README.md and CHANGELOG.md -->"

# Each README Docs row -> the object in the scene that shows it. Rows not listed here go on the docs board.
SCENE = {
    "docs/configuration.md": ("helm", "The helm"),
    "docs/dependencies.md": ("hold", "The cargo hold"),
    "docs/fleet-guards.md": ("lantern", "The bow lantern"),
    "docs/herdr.md": ("nest", "The crow's nest"),
    "herdr-patch/README.md": ("spyglass", "The spyglass"),
    "docs/omp.md": ("mast", "The mast"),
    "docs/chat.md": ("antenna", "The radio mast"),
    "docs/imessage.md": ("bell", "The ship's bell"),
    "docs/capacity.md": ("barrels", "The barrels"),
    "docs/ci-pool.md": ("containers", "The containers"),
    "docs/architecture.md": ("lighthouse", "The lighthouse"),
    "docs/recovery.md": ("lifeboat", "The lifeboat"),
    "docs/security.md": ("cabin", "The cabin"),
    "docs/secrets.md": ("strongbox", "The strongbox"),
    "docs/google-workspace.md": ("mailbox", "The mailbox"),
    "docs/agent-host-move.md": ("tender", "The tender"),
}


def features(readme):
    """(title, link, description) for each row of the README's Docs table."""
    section = readme.split("\n## Docs\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| \[([^\]]+)\]\(([^)]+)\) \| (.+?) \|$", section, re.M)


def inline(text, limit=None):
    """Markdown inline text as HTML: links become their words, code spans stay code."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).replace("**", "")
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "\u2026"
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def first_sentence(markdown):
    prose = next(p for p in markdown.split("\n\n") if p.strip() and p.strip()[0] not in "#<[!|>`-")
    return " ".join(prose.replace("**", "").split()).split(". ", 1)[0].rstrip(".") + "."


def points(readme, changelog):
    """(spot, title, href, body HTML) for every point of interest."""
    rows, extra = [], []
    for title, link, desc in features(readme):
        href = f"{REPO}/blob/main/{link}"
        if link in SCENE:
            rows.append((SCENE[link][0], title, href, f"{SCENE[link][1]}. {inline(desc)}"))
        else:
            print(
                f"harbor: no scene object for {link}; listing it on the docs board", file=sys.stderr
            )
            extra.append(
                f'<a target="_blank" rel="noopener" href="{href}">{html.escape(title)}</a>: {inline(desc, 60)}'
            )
    if extra:
        rows.append(
            (
                "docsboard",
                "More docs",
                f"{REPO}#docs",
                "The docs board. More pages: " + "; ".join(extra),
            )
        )
    version = re.search(r"^## \[(\d[^\]]*)\]", changelog, re.M).group(1)
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    news = [
        re.sub(r"\s*\(\[#\d+\].*$", "", item)
        for item in re.findall(r"^- (.+)$", unreleased, re.M)[:3]
    ]
    quick = readme.split("\n## Quick start\n", 1)[1]
    rows += [
        (
            "gangway",
            "Quick start",
            f"{REPO}#quick-start",
            f"The gangway. {inline(first_sentence(quick))}",
        ),
        (
            "sign",
            "Crewship on GitHub",
            REPO,
            f"The name on the bow. {inline(first_sentence(readme))}",
        ),
        (
            "office",
            f"Releases (v{version})",
            f"{REPO}/releases",
            f"The harbor office. The latest release is v{version}."
            + (
                " Coming next: " + "; ".join(inline(item, 90) for item in news) + "."
                if news
                else ""
            ),
        ),
        (
            "how",
            "How this is built",
            "how.html",
            "The notice board. How this harbor is drawn in text, how you move, and how it deploys.",
        ),
    ]
    return rows


def build(dist=HARBOR / "dist"):
    readme = (ROOT / "README.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    items = "\n".join(
        f'      <li data-spot="{spot}"><a target="_blank" rel="noopener" href="{href}">'
        f"{html.escape(title)}</a><p>{body}</p></li>"
        for spot, title, href, body in points(readme, changelog)
    )
    shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(HARBOR / "public", dist)
    page = dist / "index.html"
    page.write_text(page.read_text().replace(MARK, items))
    return dist


if __name__ == "__main__":
    print(build())
