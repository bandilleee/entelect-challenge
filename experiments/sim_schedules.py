"""Deterministic reference schedules used by the other ``sim_*`` experiments.

No RNG, no wall clock: every schedule is a pure function of the world.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.sim import make_schedule
from src.world import World

LEVEL1_SPECIES = (1, 2, 5, 6, 12)  # Grass, Rose Bush, Dwarf Sunflower, Lavender, Oak


def plantable_cells(world: World, soils=(0, 1)) -> list[tuple[int, int]]:
    """Row-major list of cells the Level-1 species can occupy."""
    ok = np.zeros((world.rows, world.cols), dtype=bool)
    for s in sorted(soils):
        ok |= world.soil == s
    ok &= world.terrain == 0
    rs, cs = np.nonzero(ok)
    return [(int(r), int(c)) for r, c in zip(rs, cs)]


def banded_schedule(world: World, n_placements: int = 2000, start_tick: int = 300,
                    per_tick: int = 20, species=LEVEL1_SPECIES):
    """~``n_placements`` placements in five contiguous row-major bands.

    Bands touch, so neighbouring species contest their shared borders - which
    is exactly what the competition-mode comparison needs to see.
    """
    cells = plantable_cells(world)
    n_band = max(1, len(cells) // len(species))
    entries = []
    for i in range(n_placements):
        r, c = cells[i % len(cells)]
        sp = species[min(len(species) - 1, (i % len(cells)) // n_band)]
        entries.append((start_tick + i // per_tick, sp, r, c))
    return make_schedule(entries)


def quarantined_schedule(world: World, n_placements: int = 2000,
                         start_tick: int = 300, per_tick: int = 20):
    """Same idea but Oak confined to the bottom band, away from the others."""
    return banded_schedule(world, n_placements, start_tick, per_tick,
                           species=(1, 2, 5, 6, 12))


def single_seed(plant_index: int, row: int, col: int, tick: int = 0):
    return make_schedule([(tick, plant_index, row, col)])
