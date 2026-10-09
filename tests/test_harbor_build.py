"""harbor/build.py fills the landing page's points of interest from the repository."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def test_every_readme_feature_has_a_point_in_the_scene(tmp_path):
    readme = (ROOT / "README.md").read_text()
    links = [link for _, link, _ in build.features(readme)]
    assert links, "no rows found in the README's Docs table"
    assert [link for link in links if link not in build.SCENE] == []

    spots = [spot for spot, *_ in build.points(readme, (ROOT / "CHANGELOG.md").read_text())]
    scene = (ROOT / "harbor/public/harbor.js").read_text()
    assert [spot for spot in spots if f'"{spot}"' not in scene] == []

    page = (build.build(tmp_path / "dist") / "index.html").read_text()
    assert page.count("<li data-spot=") == len(spots)
