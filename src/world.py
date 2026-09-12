"""Level / plant-dataset loading for the Photospheria simulator.

Nothing here is level-1 specific: every path is an argument, and cells missing
from the level file default to ``terrain=0, soil=0`` (dirt) as established in
``harness/problem-spec.md``.

Determinism: no RNG, no wall-clock, no iteration over unordered sets in any
code path that can reach an output.  Every collection that is iterated is
either a list in file order or explicitly sorted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

# Terrain codes
TERRAIN_PLANTABLE = 0
TERRAIN_WATER = 1
TERRAIN_STONE = 2

# Soil codes
SOIL_DIRT = 0
SOIL_MUD = 1
SOIL_CLAY = 2
SOIL_BURNT = 3

SEASONS = ("Spring", "Summer", "Autumn", "Winter")

SPREAD_TYPES = ("VonNeumann", "Moore", "Row", "Column", "CrossHatch")


# --------------------------------------------------------------------------
# Plants
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Plant:
    """One row of ``plant_dataset.json``, flattened."""

    index: int
    name: str
    time_to_maturity: int
    spread_rate: int
    spread_mechanism: str
    spread_type: str
    spread_range: int
    root_type: str
    invasiveness_rank: int
    preferred_soil: tuple[int, ...]
    weaknesses: Mapping[str, Any]  # rule type -> value (None when valueless)
    special: Mapping[str, Any]
    role: str
    conditional_modifiers: tuple[Any, ...] = ()

    # -- convenience predicates used by the simulator ----------------------
    @property
    def no_shade_survival(self) -> bool:
        return "no_shade_survival" in self.weaknesses

    @property
    def no_shade_spread(self) -> bool:
        return "no_shade_spread" in self.weaknesses

    @property
    def no_winter_spread(self) -> bool:
        return "no_winter_spread" in self.weaknesses

    @property
    def adjacent_shade_penalty(self) -> bool:
        return "adjacent_shade_penalty" in self.special

    @property
    def shade_radius(self) -> int:
        v = self.special.get("shade_radius")
        return int(v) if v is not None else 0

    @property
    def coexist_all_species(self) -> bool:
        return "coexist_all_species" in self.special

    @property
    def subsurface_growth(self) -> bool:
        return "subsurface_growth" in self.special


def _rule_map(entries: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """``[{"type":"shade_radius","value":4}]`` -> ``{"shade_radius": 4}``."""
    out: dict[str, Any] = {}
    for e in entries or ():
        out[str(e["type"])] = e.get("value")
    return out


def load_plants(path: str) -> dict[int, Plant]:
    """Load ``plant_dataset.json`` into ``{index: Plant}``."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    plants: dict[int, Plant] = {}
    for entry in raw:
        g = entry["growth"]
        rules = entry.get("rules", {}) or {}
        p = Plant(
            index=int(entry["index"]),
            name=str(entry["plant"]),
            time_to_maturity=int(g["time_to_maturity"]),
            spread_rate=int(g["spread_rate"]),
            spread_mechanism=str(g.get("spread_mechanism", "")),
            spread_type=str(g["spread_type"]),
            spread_range=int(g["spread_range"]),
            root_type=str(g.get("root_type", "")),
            invasiveness_rank=int(g["invasiveness_rank"]),
            preferred_soil=tuple(int(s) for s in entry.get("preferred_soil", ())),
            weaknesses=_rule_map(rules.get("weaknesses")),
            special=_rule_map(rules.get("special")),
            role=str(entry.get("role", "")),
            conditional_modifiers=tuple(g.get("conditional_modifiers", ()) or ()),
        )
        plants[p.index] = p
    return plants


# --------------------------------------------------------------------------
# World
# --------------------------------------------------------------------------
@dataclass
class World:
    rows: int
    cols: int
    ticks: int
    animals_enabled: bool
    terrain: np.ndarray  # int8 (rows, cols)
    soil: np.ndarray  # int8 (rows, cols)
    season_schedule: tuple[tuple[int, str], ...]  # sorted by tick, ascending
    commands: tuple[Mapping[str, Any], ...] = ()
    initial_season: str = "Spring"
    path: str = ""
    #: ``{"type":"event","tick":250,"event":"Rain"}`` entries, sorted by tick.
    #: An event "has transpired at least once" from its tick onwards, so the
    #: unlock leaf that reads it latches - see :mod:`src.animals`.
    event_schedule: tuple[tuple[int, str], ...] = ()

    # cached season lookup table, built lazily
    _season_by_tick: list[str] | None = field(default=None, repr=False, compare=False)

    def season_at(self, tick: int) -> str:
        """Season in force *during* ``tick``.

        A ``season`` command at tick K takes effect at the start of tick K
        (the ``season`` phase runs first in the default phase order).
        """
        season = self.initial_season
        for cmd_tick, name in self.season_schedule:
            if cmd_tick <= tick:
                season = name
            else:
                break
        return season

    def season_table(self, n_ticks: int | None = None) -> list[str]:
        """Precomputed season per tick, index 0..n_ticks-1."""
        n = self.ticks if n_ticks is None else n_ticks
        if self._season_by_tick is not None and len(self._season_by_tick) >= n:
            return self._season_by_tick
        table: list[str] = []
        season = self.initial_season
        sched = list(self.season_schedule)
        j = 0
        for t in range(n):
            while j < len(sched) and sched[j][0] <= t:
                season = sched[j][1]
                j += 1
            table.append(season)
        self._season_by_tick = table
        return table

    def events_by_tick(self, n_ticks: int | None = None) -> list[tuple[str, ...]]:
        """Per tick, the events that have transpired up to and including it."""
        n = self.ticks if n_ticks is None else n_ticks
        table: list[tuple[str, ...]] = []
        seen: list[str] = []
        sched = list(self.event_schedule)
        j = 0
        for t in range(n):
            while j < len(sched) and sched[j][0] <= t:
                if sched[j][1] not in seen:
                    seen.append(sched[j][1])
                j += 1
            table.append(tuple(sorted(seen)))
        return table

    @property
    def plantable(self) -> np.ndarray:
        """Bool mask: terrain allows a plant at all (soil still filters)."""
        return self.terrain == TERRAIN_PLANTABLE

    def soil_mask(self, preferred_soil: Sequence[int]) -> np.ndarray:
        """Cells a plant with ``preferred_soil`` may occupy."""
        ok = np.zeros((self.rows, self.cols), dtype=bool)
        for s in sorted(set(int(x) for x in preferred_soil)):
            ok |= self.soil == s
        ok &= self.plantable
        return ok


def load_world(path: str, initial_season: str = "Spring") -> World:
    """Parse a level JSON file into a :class:`World`.

    ``path`` is always an argument - never hard-coded.  Level files contain
    parentheses in their filenames, so quote them in shell commands.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    rows = int(raw["rows"])
    cols = int(raw["cols"])

    terrain = np.zeros((rows, cols), dtype=np.int8)
    soil = np.zeros((rows, cols), dtype=np.int8)

    for cell in raw.get("cells", ()) or ():
        r = int(cell["row"])
        c = int(cell["col"])
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        terrain[r, c] = int(cell.get("terrain", 0))
        soil[r, c] = int(cell.get("soil", 0))

    commands = tuple(raw.get("commands", ()) or ())
    seasons = sorted(
        (
            (int(c["tick"]), str(c["season"]))
            for c in commands
            if str(c.get("type", "")) == "season"
        ),
        key=lambda x: x[0],
    )
    events = sorted(
        (
            (int(c["tick"]), str(c["event"]))
            for c in commands
            if str(c.get("type", "")) == "event"
        ),
        key=lambda x: (x[0], x[1]),
    )

    return World(
        rows=rows,
        cols=cols,
        ticks=int(raw["ticks"]),
        animals_enabled=bool(raw.get("animals_enabled", False)),
        terrain=terrain,
        soil=soil,
        season_schedule=tuple(seasons),
        commands=commands,
        initial_season=initial_season,
        path=path,
        event_schedule=tuple(events),
    )
