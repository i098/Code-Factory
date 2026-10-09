import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sponsors", Path(__file__).parents[1] / "scripts/sponsors.py"
)
sponsors = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sponsors)

README = Path(__file__).parents[1] / "README.md"


def response(*entities):
    nodes = [{"sponsorEntity": entity} for entity in entities]
    return {"data": {"user": {"sponsorshipsAsMaintainer": {"nodes": nodes}}}}


def test_no_sponsors_leaves_the_committed_readme_unchanged():
    # An unchanged README is what keeps the workflow from opening a pull request.
    text = README.read_text()
    assert sponsors.replace(text, sponsors.logins(response())) == text
    assert sponsors.FALLBACK in text


def test_sponsors_replace_the_fallback_and_keep_the_rest():
    text = "intro\n<!-- sponsors -->\nold\n<!-- /sponsors -->\noutro\n"
    found = sponsors.logins(response({"login": "alice"}, None, {"login": "acme-org"}))
    assert sponsors.replace(text, found) == (
        "intro\n<!-- sponsors -->\n"
        "- [@alice](https://github.com/alice)\n"
        "- [@acme-org](https://github.com/acme-org)\n"
        "<!-- /sponsors -->\noutro\n"
    )


def test_the_last_sponsor_leaving_restores_the_fallback():
    listed = sponsors.replace("<!-- sponsors -->\n<!-- /sponsors -->", ["alice"])
    assert sponsors.replace(listed, []) == (
        f"<!-- sponsors -->\n{sponsors.FALLBACK}\n<!-- /sponsors -->"
    )


@pytest.mark.parametrize("text", ["no markers", "<!-- /sponsors --> <!-- sponsors -->"])
def test_missing_or_reversed_markers_fail(text):
    with pytest.raises(SystemExit):
        sponsors.replace(text, ["alice"])
