#!/usr/bin/env python3
"""Score a schedule against the simulator, across the rule settings we are unsure of.

Usage:
    python experiments/eval_schedule.py <level.json> <schedule.json>

The two genuinely undetermined rules -- `spread_clock` and `competition` -- are
swept rather than assumed. A schedule that only scores well under one setting is
a schedule we cannot trust, because we have no way to find out which setting the
organisers used until we submit.
"""
import dataclasses
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.score import score, sweep                     # noqa: E402
from src.sim import Rules, simulate                    # noqa: E402
from src.world import load_plants, load_world          # noqa: E402

NAMES = {1: "Grass", 2: "Rose Bush", 5: "Sunflower", 6: "Lavender", 12: "Oak"}
DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"


def evaluate(world, plants, schedule, **overrides):
    rules = dataclasses.replace(Rules(), **overrides)
    state = simulate(world, plants, schedule, rules=rules)
    d = state.to_dict()
    return d, sweep(d), score(d, alpha=1.0, k=1.0)


def main():
    level, sched_path = sys.argv[1], sys.argv[2]
    world = load_world(level)
    plants = load_plants(str(DATA / "plant_dataset.json"))
    schedule = json.loads(pathlib.Path(sched_path).read_text())

    n = sum(len(a["plants"]) for a in schedule["actions"])
    print(f"schedule: {n} placements over {len(schedule['actions'])} ticks\n")

    header = (f"{'spread_clock':<20}{'competition':<12}{'C':>6}{'H':>9}"
              f"{'cover':>8}{'a=k=1':>9}{'worst':>9}{'mean':>9}   species split")
    print(header)
    print("-" * len(header))

    rows = []
    for clock in ("since_maturity", "delayed_maturity"):
        for comp in ("hybrid", "rank", "last_wins"):
            d, sw, s1 = evaluate(world, plants, schedule,
                                 spread_clock=clock, competition=comp)
            counts = {}
            for row in d["grid"]:
                for v in row:
                    if v:
                        counts[v] = counts.get(v, 0) + 1
            split = " ".join(
                f"{NAMES.get(i, i)[:4]}={counts.get(i, 0)}"
                for i in (1, 2, 6, 5, 12)
            )
            print(f"{clock:<20}{comp:<12}{s1.C:>6}{s1.H:>9.4f}"
                  f"{s1.coverage:>8.3f}{s1.final:>9.4f}"
                  f"{sw.worst:>9.4f}{sw.mean:>9.4f}   {split}")
            rows.append((clock, comp, sw.worst, sw.mean))

    print()
    worst_case = min(r[2] for r in rows)
    mean_case = sum(r[3] for r in rows) / len(rows)
    print(f"worst across all rule settings and all (alpha,k): {worst_case:.4f}")
    print(f"mean  across all rule settings:                   {mean_case:.4f}")


if __name__ == "__main__":
    main()
