"""ASCII rendering of a simulator :class:`~src.sim.State`.

Visual debugging is the primary way we will sanity-check the simulator, so the
renderer takes any state - including intermediate ones captured through
``simulate(..., record=...)``.

Legend (empty cells):
    ``.`` dirt   ``-`` mud   ``,`` clay   ``%`` burnt   ``~`` water   ``#`` stone

Occupied cells use one stable character per plant index (see ``PLANT_CHARS``).
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .world import (SOIL_BURNT, SOIL_CLAY, SOIL_DIRT, SOIL_MUD,
                    TERRAIN_PLANTABLE, TERRAIN_STONE, TERRAIN_WATER, World)

EMPTY_DIRT = "."
EMPTY_MUD = "-"
EMPTY_CLAY = ","
EMPTY_BURNT = "%"
WATER = "~"
STONE = "#"

#: Fixed, deterministic character per plant index (1..31).  The five Level-1
#: species get mnemonic letters; the rest are filled in stably.
PLANT_CHARS: dict[int, str] = {
    1: "g",   # Grass
    2: "R",   # Rose Bush
    3: "b",   # Blue Moss
    4: "v",   # Crimson Vine
    5: "S",   # Dwarf Sunflower
    6: "L",   # Lavender
    7: "o",   # Orange Blossom
    8: "t",   # Stone Reed
    9: "x",   # Crystal Cactus
    10: "m",  # Mire Bloom
    11: "f",  # Fern
    12: "O",  # Oak Tree
}
_FILL = "ABCDEFGHIJKLMNPQTUVWXYZ"
for _i in range(13, 32):
    PLANT_CHARS.setdefault(_i, _FILL[(_i - 13) % len(_FILL)])


def _terrain_chars(world: World) -> np.ndarray:
    base = np.full((world.rows, world.cols), EMPTY_DIRT, dtype="<U1")
    base[world.soil == SOIL_MUD] = EMPTY_MUD
    base[world.soil == SOIL_CLAY] = EMPTY_CLAY
    base[world.soil == SOIL_BURNT] = EMPTY_BURNT
    base[world.terrain == TERRAIN_WATER] = WATER
    base[world.terrain == TERRAIN_STONE] = STONE
    return base


def render_ascii(state: Any, world: World | None = None, header: bool = True,
                 gutter: bool = True) -> str:
    """Render ``state`` as one character per cell."""
    world = world if world is not None else getattr(state, "world", None)
    grid = np.asarray(state.grid)
    rows, cols = grid.shape

    if world is not None:
        chars = _terrain_chars(world)
    else:
        chars = np.full((rows, cols), EMPTY_DIRT, dtype="<U1")

    for idx in sorted(set(int(v) for v in np.unique(grid)) - {0}):
        chars[grid == idx] = PLANT_CHARS.get(idx, "?")

    lines: list[str] = []
    pad = " " * 4 if gutter else ""
    if header:
        tick = getattr(state, "tick", None)
        season = getattr(state, "season", None)
        bits = []
        if tick is not None:
            bits.append(f"tick={tick}")
        if season:
            bits.append(f"season={season}")
        bits.append(f"populated={int((grid != 0).sum())}")
        lines.append(" ".join(bits))
        if cols <= 200:
            lines.append(pad + "".join(str((c // 10) % 10) for c in range(cols)))
            lines.append(pad + "".join(str(c % 10) for c in range(cols)))
    for r in range(rows):
        prefix = f"{r:3d} " if gutter else ""
        lines.append(prefix + "".join(chars[r]))
    return "\n".join(lines)


def legend(plants: Mapping[int, Any] | None = None) -> str:
    """Human-readable legend for whatever species are in the dataset."""
    out = [f"{EMPTY_DIRT} dirt   {EMPTY_MUD} mud   {EMPTY_CLAY} clay   "
           f"{EMPTY_BURNT} burnt   {WATER} water   {STONE} stone"]
    if plants:
        for idx in sorted(plants):
            out.append(f"{PLANT_CHARS.get(idx, '?')} {plants[idx].name} ({idx})")
    return "\n".join(out)
