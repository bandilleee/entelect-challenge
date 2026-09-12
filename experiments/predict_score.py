#!/usr/bin/env python3
"""Predict the leaderboard score for a schedule, analytically.

The scoring parameters are no longer unknown. The evaluation log for our first
submission pinned all three exactly:

    leaderboard constant = 1e9      0.274709453230 * 1e9 = 274709453
    alpha                = 1.0      main / H = 0.720000000000 = density
    k                    = 1.0      solved from our own placement ticks

and with alpha = k = 1 the whole score collapses to something linear:

    final = 0.8 * H * (C / C_max)  +  0.2 * (1 / C_max) * SUM(l_ij / T)

The model of the ENGINE used here is equally empirical: for a schedule that
fills every usable cell, the final grid is the placement list. The engine's log
returned three of five species at exactly the placed count, and the other two
off by ten cells. There is nowhere for a plant to spread when every cell is
already occupied, so spread barely fires. That is a much better model of the
engine than our own simulator, which predicted large drift that did not happen.

This predictor is therefore only valid for dense, fill-everything schedules.
For anything relying on spread or on the dead-matter cycle, use src/sim.py and
treat the answer with suspicion until a submission confirms it.

Usage: python experiments/predict_score.py <level.json> <schedule.json>
"""
import collections
import json
import math
import pathlib
import sys

ALPHA = 1.0
K = 1.0
BIG = 1e9
CATALOGUE = 31

NAMES = {1: "Grass", 2: "Rose Bush", 5: "Dwarf Sunflower",
         6: "Lavender", 12: "Oak Tree"}


def predict(level_path, schedule_path):
    world = json.loads(pathlib.Path(level_path).read_text())
    sched = json.loads(pathlib.Path(schedule_path).read_text())
    c_max = world["rows"] * world["cols"]
    T = world["ticks"]

    counts = collections.Counter()
    lifespans = []
    for action in sched["actions"]:
        for p in action["plants"]:
            counts[p["plant_index"]] += 1
            lifespans.append(T - action["tick"])

    C = sum(counts.values())
    H = 0.0
    for n in counts.values():
        p = n / C
        H -= p * math.log(p, CATALOGUE)

    main = H * (C / c_max) ** ALPHA
    longevity = sum((l / T) ** K for l in lifespans) / c_max
    final = 0.8 * main + 0.2 * longevity
    return dict(C=C, H=H, coverage=C / c_max, main=main, longevity=longevity,
                final=final, leaderboard=final * BIG, counts=counts,
                mean_life=sum(lifespans) / len(lifespans))


def main():
    r = predict(sys.argv[1], sys.argv[2])
    print(f"  C           {r['C']}   coverage {r['coverage']:.4f}")
    print(f"  species     " + "  ".join(
        f"{NAMES.get(i, i)}={n}" for i, n in sorted(r["counts"].items())))
    print(f"  H           {r['H']:.6f}   (ceiling for 5 species "
          f"{math.log(5, CATALOGUE):.6f})")
    print(f"  mean life   {r['mean_life']:.1f} ticks")
    print(f"  main        {r['main']:.6f}")
    print(f"  longevity   {r['longevity']:.6f}")
    print(f"  final       {r['final']:.9f}")
    print(f"  LEADERBOARD {r['leaderboard']:,.0f}")


if __name__ == "__main__":
    main()
