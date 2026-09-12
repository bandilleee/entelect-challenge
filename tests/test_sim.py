"""Single-rule tests for the simulator, run against the Level-1 fixture.

``resources-docs/1(1).json`` is a synthetic calibration harness - stone-walled
single-soil plots plus two water boxes - so each rule can be exercised in
isolation by seeding inside a plot and switching every other rule off.

    python -m pytest tests/test_sim.py -q

Each test names the ONE mechanic it pins down.  Nothing here asserts a number
that was not produced by running the simulator - but every assertion is a
consequence of the rule as written in ``harness/problem-spec.md``, not a
snapshot of whatever the code happened to do.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.render import render_ascii  # noqa: E402
from src.sim import (Rules, coverage, make_schedule, simulate,  # noqa: E402
                     spread_offsets, species_counts)
from src.world import load_plants, load_world  # noqa: E402

LEVEL = str(ROOT / "resources-docs" / "1(1).json")
DATASET = str(ROOT / "resources-docs" / "plant_dataset.json")

GRASS, ROSE, SUNFLOWER, LAVENDER, OAK = 1, 2, 5, 6, 12

# A cell deep inside the open dirt band (rows 20-29 are unobstructed dirt).
OPEN = (24, 25)


@pytest.fixture(scope="module")
def world():
    return load_world(LEVEL)


@pytest.fixture(scope="module")
def plants():
    return load_plants(DATASET)


def run(world, plants, entries, ticks, rules=None, **kw):
    rules = rules or Rules()
    return simulate(world, plants, make_schedule(entries), rules,
                    n_ticks=ticks, **kw)


# ==========================================================================
# world loading
# ==========================================================================
def test_unlisted_cells_default_to_dirt(world):
    """Cells absent from ``cells`` are terrain 0 / soil 0."""
    assert world.rows == 50 and world.cols == 50 and world.ticks == 500
    assert world.animals_enabled is False
    assert world.terrain[25, 25] == 0 and world.soil[25, 25] == 0
    counts = {
        "dirt": int(((world.soil == 0) & (world.terrain == 0)).sum()),
        "mud": int((world.soil == 1).sum()),
        "clay": int((world.soil == 2).sum()),
        "water": int((world.terrain == 1).sum()),
        "stone": int((world.terrain == 2).sum()),
    }
    assert counts == {"dirt": 1440, "mud": 360, "clay": 360,
                      "water": 180, "stone": 160}


def test_season_schedule(world):
    assert world.season_schedule == ((100, "Summer"), (200, "Autumn"),
                                     (300, "Winter"), (400, "Spring"))
    assert world.season_at(0) == "Spring"      # before the first command
    assert world.season_at(99) == "Spring"
    assert world.season_at(100) == "Summer"    # command applies ON its tick
    assert world.season_at(350) == "Winter"
    assert world.season_at(499) == "Spring"


# ==========================================================================
# rule 3 - spread geometry
# ==========================================================================
def test_spread_geometry_offsets():
    assert spread_offsets("VonNeumann", 1) == ((-1, 0), (0, -1), (0, 1), (1, 0))
    assert len(spread_offsets("Moore", 2)) == 24
    assert spread_offsets("Row", 1) == ((0, -1), (0, 1))
    assert spread_offsets("Column", 1) == ((-1, 0), (1, 0))
    # CrossHatch read as the diagonal X
    assert spread_offsets("CrossHatch", 1) == ((-1, -1), (-1, 1), (1, -1), (1, 1))
    assert spread_offsets("CrossHatch", 2) == ((-2, -2), (-2, 2), (-1, -1),
                                               (-1, 1), (1, -1), (1, 1),
                                               (2, -2), (2, 2))


@pytest.mark.parametrize("ticks,cells", [(1, 1), (2, 5), (3, 13), (4, 25), (5, 41)])
def test_grass_von_neumann_diamond_exact(world, plants, ticks, cells):
    """Rule 3 alone: a Grass wave is an exact Manhattan diamond.

    Grass (maturity 1) spreads on the tick it matures and every seedling does
    the same one tick after birth, so the front advances exactly one cell per
    tick: |dr|+|dc| <= t, i.e. 1 + 2t(t+1) cells.
    """
    rules = Rules(nutrient_drain=False, shade=False)
    st = run(world, plants, [(0, GRASS, *OPEN)], ticks, rules)
    assert coverage(st) == cells
    # and it really is the diamond, not just the right cardinality
    r0, c0 = OPEN
    rr, cc = np.nonzero(st.grid == GRASS)
    assert (np.abs(rr - r0) + np.abs(cc - c0)).max(initial=0) <= ticks - 1


# ==========================================================================
# rule 4 - soil filtering / containment
# ==========================================================================
def test_placement_on_clay_is_ignored(world, plants):
    """No Level-1 species lists soil 2, so a clay placement silently fails."""
    assert world.soil[5, 35] == 2
    st = run(world, plants, [(0, GRASS, 5, 35)], 3, Rules(nutrient_drain=False))
    assert coverage(st) == 0


def test_placement_on_water_and_stone_is_ignored(world, plants):
    st = run(world, plants,
             [(0, GRASS, 0, 11), (0, GRASS, 0, 10)], 3,
             Rules(nutrient_drain=False))
    assert coverage(st) == 0


def test_grass_never_escapes_stone_water_or_clay(world, plants):
    """Containment: stone, water and clay are hard walls for every starter."""
    rules = Rules(nutrient_drain=False, shade=False)
    st = run(world, plants, [(0, GRASS, 10, 25)], 120, rules)  # mud plot
    occ = st.grid != 0
    assert not (occ & (world.terrain != 0)).any(), "escaped onto water/stone"
    assert not (occ & (world.soil == 2)).any(), "escaped onto clay"
    # it did fill its own mud plot and leak into the open dirt band only
    assert int((occ & (world.soil == 1)).sum()) == 360
    assert coverage(st) > 360


def test_soil_filter_off_lets_grass_onto_clay(world, plants):
    """The same run with rule 4 disabled reaches clay - proving the isolation."""
    rules = Rules(nutrient_drain=False, shade=False, soil_filter=False)
    st = run(world, plants, [(0, GRASS, 10, 25)], 120, rules)
    assert int(((st.grid != 0) & (world.soil == 2)).sum()) > 0


# ==========================================================================
# rule 2 - maturity clock
# ==========================================================================
def test_maturity_clock_gates_first_spread(world, plants):
    """Rose Bush has time_to_maturity 10: no spread before it matures."""
    rules = Rules(nutrient_drain=False, shade=False)
    for t in range(1, 11):
        st = run(world, plants, [(0, ROSE, *OPEN)], t, rules)
        assert coverage(st) == 1, f"Rose spread too early at tick {t - 1}"
    st = run(world, plants, [(0, ROSE, *OPEN)], 12, rules)
    assert coverage(st) > 1


def test_maturity_disabled_spreads_immediately(world, plants):
    rules = Rules(nutrient_drain=False, shade=False, maturity=False)
    st = run(world, plants, [(0, ROSE, *OPEN)], 3, rules)
    assert coverage(st) > 1


# ==========================================================================
# rule 1 - nutrients, death, dead matter
# ==========================================================================
def test_nutrient_drain_kills_after_100_ticks(world, plants):
    """100 nutrients, -1/tick while occupied, death at <= 0."""
    rules = Rules(spread=False, shade=False)
    st = run(world, plants, [(0, GRASS, *OPEN)], 99, rules)
    assert st.grid[OPEN] == GRASS and st.lifespan[OPEN] == 99
    st = run(world, plants, [(0, GRASS, *OPEN)], 100, rules)
    assert st.grid[OPEN] == 0 and st.lifespan[OPEN] == 0
    assert st.dead_matter[OPEN]           # cell flagged as dead matter
    assert st.nutrient[OPEN] == pytest.approx(0.0)  # exhausted, regen starts next tick


def test_nutrients_disabled_means_immortal(world, plants):
    rules = Rules(nutrient_drain=False, spread=False, shade=False)
    st = run(world, plants, [(0, GRASS, *OPEN)], 400, rules)
    assert st.grid[OPEN] == GRASS and st.lifespan[OPEN] == 400


def test_dead_matter_regenerates_then_halves_the_drain(world, plants):
    """Rule 8: a second generation on dead matter lives ~2x as long.

    gen-1 dies at tick 99 leaving 0 nutrients; the empty cell regenerates
    +1/tick back to 100 by tick 199; gen-2 planted at 200 drains 0.5/tick.
    """
    rules = Rules(spread=False, shade=False)
    entries = [(0, GRASS, *OPEN), (200, GRASS, *OPEN)]
    st = run(world, plants, entries, 200, rules)
    assert st.nutrient[OPEN] == pytest.approx(100.0)  # fully regenerated

    st = run(world, plants, entries, 380, rules)
    assert st.grid[OPEN] == GRASS, "gen-2 should still be alive at tick 379"
    assert st.lifespan[OPEN] == 180

    # with rule 8 off it drains at the full rate and is already dead
    st = run(world, plants, entries, 380,
             Rules(spread=False, shade=False, dead_matter_reentry=False))
    assert st.grid[OPEN] == 0


def test_nothing_enters_an_exhausted_cell(world, plants):
    """A cell at 0 nutrients is uninhabitable until it regenerates."""
    rules = Rules(spread=False, shade=False)
    st = run(world, plants, [(0, GRASS, *OPEN), (100, GRASS, *OPEN)], 102, rules)
    assert st.grid[OPEN] == 0


# ==========================================================================
# rule 6 - shade
# ==========================================================================
def test_oak_shade_kills_grass(world, plants):
    """Oak matures at 20 and shades radius 4; Grass has no_shade_survival."""
    r, c = OPEN
    entries = [(0, OAK, r, c), (0, GRASS, r, c + 3)]
    rules = Rules(nutrient_drain=False, spread=False)
    alive = run(world, plants, entries, 19, rules)
    assert alive.grid[r, c + 3] == GRASS, "shade before the Oak matured"
    dead = run(world, plants, entries, 21, rules)
    assert dead.grid[r, c + 3] == 0, "Grass survived inside the Oak's shade"
    # ... and it is the shade rule doing it
    off = run(world, plants, entries, 21,
              Rules(nutrient_drain=False, spread=False, shade=False))
    assert off.grid[r, c + 3] == GRASS


def test_shade_radius_is_four_and_square(world, plants):
    r, c = OPEN
    rules = Rules(nutrient_drain=False, spread=False)
    inside = run(world, plants, [(0, OAK, r, c), (0, GRASS, r + 4, c + 4)],
                 21, rules)
    outside = run(world, plants, [(0, OAK, r, c), (0, GRASS, r + 5, c)],
                  21, rules)
    assert inside.grid[r + 4, c + 4] == 0      # Chebyshev distance 4: shaded
    assert outside.grid[r + 5, c] == GRASS     # distance 5: not shaded


def test_sunflower_cannot_spread_in_shade(world, plants):
    """no_shade_spread: the Sunflower survives but stops spreading."""
    r, c = OPEN
    # Chebyshev distance 4: inside the Oak's shade, outside its 2-cell spread
    # reach for the 30 ticks this runs (its seedlings mature only at tick 40).
    seed = (r + 4, c + 4)
    entries = [(0, OAK, r, c), (0, SUNFLOWER, *seed)]
    rules = Rules(nutrient_drain=False)
    st = run(world, plants, entries, 30, rules)
    assert st.grid[seed] == SUNFLOWER                  # survives - only spread stops
    free = run(world, plants, [(0, SUNFLOWER, *seed)], 30, rules)
    assert species_counts(st)[SUNFLOWER] < species_counts(free)[SUNFLOWER]


# ==========================================================================
# rule 7 - seasons
# ==========================================================================
def test_lavender_does_not_spread_in_winter(world, plants):
    """Winter is ticks 300-399 (Spring returns at 400)."""
    rules = Rules(nutrient_drain=False, shade=False)
    seed = [(290, LAVENDER, *OPEN)]
    at_310 = coverage(run(world, plants, seed, 310, rules))
    at_399 = coverage(run(world, plants, seed, 400, rules))
    at_410 = coverage(run(world, plants, seed, 411, rules))
    assert at_310 == at_399, "Lavender spread during Winter"
    assert at_410 > at_399, "Lavender did not resume in Spring"

    off = Rules(nutrient_drain=False, shade=False, season_spread=False)
    assert coverage(run(world, plants, seed, 400, off)) > at_399


def test_grass_ignores_winter(world, plants):
    rules = Rules(nutrient_drain=False, shade=False)
    seed = [(290, GRASS, *OPEN)]
    assert coverage(run(world, plants, seed, 340, rules)) > \
           coverage(run(world, plants, seed, 310, rules))


# ==========================================================================
# rule 5 - competition
# ==========================================================================
def test_competition_modes_differ_on_an_occupied_cell(world, plants):
    """Grass (rank 1) walking into a Rose Bush (rank 2).

    rank / hybrid: rank decides, so Grass bounces off.
    last_wins:     arrival decides, so Grass takes the cell.
    """
    r, c = OPEN
    entries = [(0, ROSE, r, c), (0, GRASS, r, c - 5)]
    rules = dict(nutrient_drain=False, shade=False)
    for mode, expected in (("rank", ROSE), ("hybrid", ROSE), ("last_wins", GRASS)):
        st = run(world, plants, entries, 10, Rules(competition=mode, **rules))
        assert st.grid[r, c] == expected, f"{mode} gave {st.grid[r, c]}"


def test_same_species_never_resets_its_own_lifespan(world, plants):
    """A spreader must not overwrite its own kind - that would reset ages."""
    rules = Rules(nutrient_drain=False, shade=False)
    st = run(world, plants, [(0, GRASS, *OPEN)], 20, rules)
    assert st.lifespan[OPEN] == 20


# ==========================================================================
# mechanics
# ==========================================================================
def test_placement_cap_is_twenty_per_tick(world, plants):
    entries = [(0, GRASS, 24, c) for c in range(25)]
    st = run(world, plants, entries, 1, Rules(nutrient_drain=False, spread=False))
    assert coverage(st) == 20
    assert st.grid[24, 19] == GRASS and st.grid[24, 20] == 0


def test_locked_plant_is_silently_ignored(world, plants):
    rules = Rules(nutrient_drain=False, spread=False,
                  allowed_plants=(GRASS, ROSE, SUNFLOWER, LAVENDER, OAK))
    st = run(world, plants, [(0, 3, *OPEN), (0, GRASS, 24, 26)], 2, rules)
    assert coverage(st) == 1 and st.grid[24, 26] == GRASS


def test_final_state_dict_shape(world, plants):
    st = run(world, plants, [(0, GRASS, *OPEN)], 5, Rules(nutrient_drain=False))
    d = st.to_dict()
    assert set(d) == {"rows", "cols", "ticks", "grid", "lifespan"}
    assert d["rows"] == 50 and d["cols"] == 50 and d["ticks"] == 500
    assert len(d["grid"]) == 50 and len(d["grid"][0]) == 50
    assert len(d["lifespan"]) == 50 and len(d["lifespan"][0]) == 50
    assert all(isinstance(v, int) for row in d["grid"] for v in row)
    assert all(isinstance(v, int) for row in d["lifespan"] for v in row)
    assert d["grid"][OPEN[0]][OPEN[1]] == GRASS
    assert d["lifespan"][OPEN[0]][OPEN[1]] == 5
    # lifespan is 0 exactly where the grid is empty
    g = np.array(d["grid"])
    ls = np.array(d["lifespan"])
    assert ((g == 0) == (ls == 0)).all()


def test_record_hook_sees_every_tick(world, plants):
    seen = []
    simulate(world, plants, make_schedule([(0, GRASS, *OPEN)]),
             Rules(nutrient_drain=False), record=lambda t, s: seen.append(t),
             n_ticks=7)
    assert seen == list(range(7))


def test_renderer_is_one_char_per_cell(world, plants):
    st = run(world, plants, [(0, GRASS, *OPEN)], 5, Rules(nutrient_drain=False))
    body = render_ascii(st, world, header=False, gutter=False).splitlines()
    assert len(body) == 50 and all(len(line) == 50 for line in body)
    assert body[0][10] == "#" and body[0][11] == "~" and body[0][31] == ","
    assert body[OPEN[0]][OPEN[1]] == "g"


def test_run_is_deterministic(world, plants):
    entries = [(t, sp, 22 + (i % 5), 5 + i) for i, (t, sp) in
               enumerate([(0, GRASS), (0, OAK), (3, ROSE), (5, LAVENDER),
                          (7, SUNFLOWER)])]
    a = run(world, plants, entries, 200).to_dict()
    b = run(world, plants, entries, 200).to_dict()
    assert a == b
