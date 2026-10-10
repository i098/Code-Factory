Closes #134

- Add the plaza fountain with blue water, a stone rim, a column, a spout, and a blue map marker.
- Preview: https://feat-cf-harbor-fountain-crewship.jerry-2c0.workers.dev
- Keep: Disconnected approaches stop safely; detour completeness remains in [#150](https://github.com/i098/Crewship/issues/150).
- Hold: Keep the mobile WebKit hold for [#143](https://github.com/i098/Crewship/issues/143).

Proof: `uv run pytest tests/test_harbor_scene.py -q`.
