#!/usr/bin/env python3
"""Fit the simulator's Rules against the three real Level 1 engine results.

We have three exact (schedule -> outcome) pairs from the organisers' evaluation
logs. The simulator predicted none of them, and two schedule changes made on its
advice cost about 65M points. Until it reproduces all three, its output is a
hint and not a measurement -- which matters far more at Level 2, where manual
placement cannot fill the grid and spread does most of the work.

This sweeps the rule flags we are genuinely unsure about and scores each
configuration on how well it reproduces the observed final species counts.

Usage: python experiments/calibrate_l1.py [--full]
"""
import dataclasses
import itertools
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import solve                                          # noqa: E402
from src.sim import Rules, simulate                   # noqa: E402
from src.world import load_plants, load_world         # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"
LEVEL = str(DATA / "1(1).json")
NAMES = {1: "Grass", 2: "Rose", 5: "Sunf", 6: "Lav", 12: "Oak"}
ORDER = [1, 2, 5, 6, 12]

EQUAL = {12: 0.2, 2: 0.2, 6: 0.2, 5: 0.2, 1: 0.2}

# The three real results. `placed` is what our solver emitted; `final` is the
# engine's plant_counts from the evaluation log.
OBSERVED = [
    dict(tag="S1  fitted seeds, ticks 407-498, 2-tick tail",
         weights=None, last_tick=498,
         final={1: 341, 2: 409, 5: 260, 6: 563, 12: 227},
         H=0.4531203007, score=274_709_453),
    dict(tag="S2  equal seeds,  ticks 401-490, 10-tick tail",
         weights=EQUAL, last_tick=490,
         final={1: 40, 2: 108, 5: 894, 6: 141, 12: 617},
         H=0.3399789173, score=209_170_416),
    dict(tag="S3  equal seeds,  ticks 410-499, 1-tick tail",
         weights=EQUAL, last_tick=499,
         final=None,                       # log not captured; H implied
         H=0.373093, score=228_005_785),
]


def build(world_json, weights, last_tick):
    """Regenerate one of the three historical schedules."""
    saved_w, saved_l = solve.SEED_WEIGHTS, solve.LAST_TICK
    try:
        if weights is not None:
            solve.SEED_WEIGHTS = weights
        solve.LAST_TICK = last_tick
        return solve.solve(world_json)
    finally:
        solve.SEED_WEIGHTS, solve.LAST_TICK = saved_w, saved_l


def counts_of(state):
    out = {i: 0 for i in ORDER}
    for row in state["grid"]:
        for v in row:
            if v in out:
                out[v] += 1
    return out


def entropy(counts):
    c = sum(counts.values())
    if not c:
        return 0.0
    return -sum((n / c) * math.log(n / c, 31) for n in counts.values() if n)


def residual(pred, obs):
    """Total cells misplaced, plus the entropy error."""
    cells = sum(abs(pred[i] - obs["final"][i]) for i in ORDER) // 2 \
        if obs["final"] else 0
    return cells, abs(entropy(pred) - obs["H"])


def main():
    full = "--full" in sys.argv
    world = load_world(LEVEL)
    plants = load_plants(str(DATA / "plant_dataset.json"))
    world_json = solve.load(LEVEL)
    schedules = [(o, build(world_json, o["weights"], o["last_tick"]))
                 for o in OBSERVED]

    grid = dict(
        spread_clock=["since_maturity", "delayed_maturity"],
        competition=["hybrid", "rank", "last_wins"],
        spread_ring_only=[False, True],
        drain_from_maturity=[False, True],
    )
    if full:
        grid["same_species_no_replace"] = [True, False]
        grid["require_nutrient_to_enter"] = [True, False]

    keys = sorted(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    print(f"{len(combos)} rule configs x {len(schedules)} schedules\n")

    results = []
    for combo in combos:
        cfg = dict(zip(keys, combo))
        rules = dataclasses.replace(Rules(), **cfg)
        cells_err = h_err = 0.0
        detail = []
        for obs, sched in schedules:
            pred = counts_of(simulate(world, plants, sched, rules=rules).to_dict())
            c, h = residual(pred, obs)
            cells_err += c
            h_err += h
            detail.append((pred, c, h))
        results.append((h_err, cells_err, cfg, detail))

    results.sort(key=lambda r: (r[0], r[1]))
    print(f"{'config':<96}{'H err':>9}{'cells':>8}")
    print("-" * 113)
    for h_err, cells_err, cfg, _ in results[:10]:
        label = "  ".join(f"{k}={v}" for k, v in sorted(cfg.items()))
        print(f"{label:<96}{h_err:>9.4f}{cells_err:>8.0f}")

    h_err, cells_err, cfg, detail = results[0]
    print(f"\nBEST CONFIG  (total H error {h_err:.4f} across three schedules)")
    for k, v in sorted(cfg.items()):
        print(f"    {k} = {v!r}")
    print()
    for (obs, _), (pred, c, h) in zip(schedules, detail):
        print(f"  {obs['tag']}")
        print("      predicted " + "  ".join(
            f"{NAMES[i]}={pred[i]}" for i in ORDER))
        if obs["final"]:
            print("      actual    " + "  ".join(
                f"{NAMES[i]}={obs['final'][i]}" for i in ORDER))
        print(f"      H predicted {entropy(pred):.4f}  actual {obs['H']:.4f}"
              f"   ({c} cells off)")


if __name__ == "__main__":
    main()
