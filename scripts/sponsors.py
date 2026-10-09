#!/usr/bin/env python3
"""Write the GitHub Sponsors of i098 between the sponsor markers of a README.

Reads the GraphQL response of `user(login: "i098") { sponsorshipsAsMaintainer }`
on stdin; .github/workflows/sponsors.yml runs it daily.
Usage: gh api graphql -f query=... | python3 scripts/sponsors.py README.md
"""

import json
import sys
from pathlib import Path

START, END = "<!-- sponsors -->", "<!-- /sponsors -->"
FALLBACK = "No sponsors yet. Be the first, and your name goes here."


def logins(response):
    nodes = response["data"]["user"]["sponsorshipsAsMaintainer"]["nodes"]
    # A deleted sponsor account comes back as a null sponsorEntity.
    return [node["sponsorEntity"]["login"] for node in nodes if node["sponsorEntity"]]


def replace(text, sponsors):
    start, end = text.find(START), text.find(END)
    if start < 0 or end < start:
        raise SystemExit(f"no {START} ... {END} markers to write the sponsors between")
    body = "\n".join(f"- [@{login}](https://github.com/{login})" for login in sponsors)
    return f"{text[: start + len(START)]}\n{body or FALLBACK}\n{text[end:]}"


if __name__ == "__main__":
    readme = Path(sys.argv[1])
    readme.write_text(replace(readme.read_text(), logins(json.load(sys.stdin))))
