#!/usr/bin/env python3
"""Which species should be planted in which time window?

The baseline assumed "least invasive first". The simulator says that assumption
is worth roughly nothing under some rule readings: the species planted earliest
has the most ticks to spread, so ordering is really about exposure time, not
invasiveness rank.

We cannot know which spread_clock / competition rules the organisers used until
we submit, so this ranks all 120 orderings by their WORST case across the rule
matrix rather than by their best. A schedule that only wins under one reading is
not a schedule, it is a bet.

Usage: python experiments/sweep_order.py <level.json> [--full]
"""
import dataclasses
import itertools
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import solve                                            # noqa: E402
from src.score import sweep                             # noqa: E402
from src.sim import Rules, simulate                     # noqa: E402
from src.world import load_plants, load_world           # noqa: E402

NAMES = {1: "Grass", 2: "Rose", 5: "Sunf", 6: "Lav", 12: "Oak"}
DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"

# The rule settings we genuinely cannot pin without a submission.
RULE_MATRIX = [
    {"spread_clock": c, "competition": k}
    for c in ("since_maturity", "delayed_maturity")
    for k in ("hybrid", "rank", "last_wins")
]


def build_schedule(world_json, order):
    """Regenerate the schedule with the species planted in `order`.

    Tick windows are derived from the seed counts inside solve(), so only the
    order needs patching here.
    """
    saved = solve.PLACEMENT_ORDER
    try:
        solve.PLACEMENT_ORDER = list(order)
        return solve.solve(world_json)
    finally:
        solve.PLACEMENT_ORDER = saved


def evaluate(world, plants, schedule):
    """Worst and mean sweep score across the whole rule matrix."""
    worst, total = float("inf"), 0.0
    for overrides in RULE_MATRIX:
        rules = dataclasses.replace(Rules(), **overrides)
        sw = sweep(simulate(world, plants, schedule, rules=rules).to_dict())
        worst = min(worst, sw.worst)
        total += sw.mean
    return worst, total / len(RULE_MATRIX)


def main():
    level = sys.argv[1]
    full = "--full" in sys.argv
    world = load_world(level)
    plants = load_plants(str(DATA / "plant_dataset.json"))
    world_json = solve.load(level)

    species = list(solve.PLACEMENT_ORDER)
    orders = list(itertools.permutations(species)) if full else [
        tuple(species),                      # baseline: least invasive first
        tuple(reversed(species)),            # most invasive first
        (12, 2, 6, 5, 1),                    # slowest-maturing first, Grass last
        (12, 5, 6, 2, 1),                    # by descending maturity
        (1, 5, 6, 2, 12),                    # Grass first, Oak last
    ]

    print(f"{len(orders)} ordering(s) x {len(RULE_MATRIX)} rule settings\n")
    print(f"{'order (early -> late)':<42}{'worst':>9}{'mean':>9}")
    print("-" * 60)

    t0 = time.time()
    results = []
    for order in orders:
        schedule = build_schedule(world_json, order)
        worst, mean = evaluate(world, plants, schedule)
        results.append((worst, mean, order))
        if not full:
            label = " -> ".join(NAMES[s] for s in order)
            print(f"{label:<42}{worst:>9.4f}{mean:>9.4f}")

    results.sort(key=lambda r: (-r[0], -r[1]))
    if full:
        print("top 10 by worst case:")
        for worst, mean, order in results[:10]:
            label = " -> ".join(NAMES[s] for s in order)
            print(f"{label:<42}{worst:>9.4f}{mean:>9.4f}")
        print("\nbottom 3:")
        for worst, mean, order in results[-3:]:
            label = " -> ".join(NAMES[s] for s in order)
            print(f"{label:<42}{worst:>9.4f}{mean:>9.4f}")

    best = results[0]
    print(f"\nBEST worst-case: {' -> '.join(NAMES[s] for s in best[2])}")
    print(f"  worst={best[0]:.4f}  mean={best[1]:.4f}")
    print(f"({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
