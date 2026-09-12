"""Visual debugging: print the grid at chosen ticks.

    python experiments/sim_render.py "resources-docs/1(1).json" 300,400,450,499
    python experiments/sim_render.py "resources-docs/1(1).json" 20 --seed 1@24,25

``--seed IDX@ROW,COL[:TICK]`` (repeatable) replaces the default banded
schedule with explicit single seeds - the fast way to look at one rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.sim_schedules import banded_schedule
from src.render import legend, render_ascii
from src.sim import Rules, make_schedule, simulate, species_counts
from src.world import load_plants, load_world


def parse_args(argv):
    level = "resources-docs/1(1).json"
    ticks = [499]
    seeds = []
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--seed":
            i += 1
            spec = argv[i]
            head, _, tick = spec.partition(":")
            idx, _, rc = head.partition("@")
            r, _, c = rc.partition(",")
            seeds.append((int(tick or 0), int(idx), int(r), int(c)))
        else:
            rest.append(argv[i])
        i += 1
    if rest:
        level = rest[0]
    if len(rest) > 1:
        ticks = [int(t) for t in rest[1].split(",")]
    return level, sorted(set(ticks)), seeds


def main() -> None:
    level, ticks, seeds = parse_args(sys.argv[1:])
    world = load_world(level)
    plants = load_plants("resources-docs/plant_dataset.json")
    sched = make_schedule(seeds) if seeds else banded_schedule(world)

    print(legend({i: plants[i] for i in sorted(plants) if i in (1, 2, 5, 6, 12)}))
    want = set(ticks)

    def rec(t, st):
        if t in want:
            print()
            print(render_ascii(st, world))
            print("counts:", species_counts(st))

    simulate(world, plants, sched, Rules(), record=rec,
             n_ticks=max(ticks) + 1)


if __name__ == "__main__":
    main()
