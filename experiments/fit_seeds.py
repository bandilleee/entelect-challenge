#!/usr/bin/env python3
"""Fit SEED_WEIGHTS so the five species finish equal, not start equal.

Equal seeding does not give an equal finish: between planting and tick 500 the
species spread into and over each other at very different rates. This runs a
deterministic feedback loop -- seed, simulate, measure the drift, seed the
gainers less and the losers more -- and prints the weights to paste into
solve.py.

Fitting is done against the WHOLE rule matrix at once, using the mean final
count across readings, because we cannot know which reading the organisers use.
Weights tuned to a single reading would be a bet, not a fit.

Usage: python experiments/fit_seeds.py <level.json> [iterations]
"""
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import solve                                            # noqa: E402
from src.score import sweep                             # noqa: E402
from src.sim import Rules, simulate                     # noqa: E402
from src.world import load_plants, load_world           # noqa: E402

NAMES = {1: "Grass", 2: "Rose", 5: "Sunf", 6: "Lav", 12: "Oak"}
DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"

RULE_MATRIX = [
    {"spread_clock": c, "competition": k}
    for c in ("since_maturity", "delayed_maturity")
    for k in ("hybrid", "rank", "last_wins")
]

# How hard to correct each round. Below 1.0 because the system over-corrects:
# shrinking a species' seed area also shrinks the frontier it spreads from, so
# the response is super-linear and a full correction oscillates.
DAMPING = 0.5
FLOOR = 0.04          # never starve a species out of the sample entirely


def measure(world, plants, weights, world_json):
    """Mean final count per species, and worst/mean score, across the matrix."""
    saved = solve.SEED_WEIGHTS
    try:
        solve.SEED_WEIGHTS = weights
        schedule = solve.solve(world_json)
    finally:
        solve.SEED_WEIGHTS = saved

    totals = {s: 0 for s in solve.PLACEMENT_ORDER}
    worst, mean_sum = float("inf"), 0.0
    for overrides in RULE_MATRIX:
        rules = dataclasses.replace(Rules(), **overrides)
        d = simulate(world, plants, schedule, rules=rules).to_dict()
        for row in d["grid"]:
            for v in row:
                if v in totals:
                    totals[v] += 1
        sw = sweep(d)
        worst = min(worst, sw.worst)
        mean_sum += sw.mean
    n = len(RULE_MATRIX)
    return ({s: totals[s] / n for s in totals}, worst, mean_sum / n)


def main():
    level = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    world = load_world(level)
    plants = load_plants(str(DATA / "plant_dataset.json"))
    world_json = solve.load(level)

    order = list(solve.PLACEMENT_ORDER)
    weights = {s: 1.0 / len(order) for s in order}
    best = None

    header = f"{'round':<7}" + "".join(f"{NAMES[s]:>17}" for s in order) + \
             f"{'worst':>9}{'mean':>9}"
    print(header)
    print("-" * len(header))

    for rnd in range(rounds):
        counts, worst, mean = measure(world, plants, weights, world_json)
        cells = sum(counts.values())
        row = f"{rnd:<7}" + "".join(
            f"{weights[s]:>8.3f}->{counts[s]:>7.0f}" for s in order
        ) + f"{worst:>9.4f}{mean:>9.4f}"
        print(row)

        if best is None or worst > best[0]:
            best = (worst, mean, dict(weights), dict(counts))

        # Seed each species in inverse proportion to how much it gained.
        target = cells / len(order)
        new = {}
        for s in order:
            ratio = target / max(counts[s], 1.0)
            new[s] = max(FLOOR, weights[s] * (1.0 + DAMPING * (ratio - 1.0)))
        total = sum(new.values())
        weights = {s: new[s] / total for s in order}

    worst, mean, w, counts = best
    print(f"\nBEST worst-case={worst:.4f}  mean={mean:.4f}")
    print("final counts:", {NAMES[s]: round(counts[s]) for s in order})
    print("\nSEED_WEIGHTS = {")
    for s in order:
        print(f"    {s}: {w[s]:.3f},   # {NAMES[s]}")
    print("}")


if __name__ == "__main__":
    main()
