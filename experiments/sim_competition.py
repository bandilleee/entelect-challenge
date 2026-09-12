"""PRIORITY EXPERIMENT - how much does competition resolution matter?

    python experiments/sim_competition.py "resources-docs/1(1).json"

The problem statement appears to contradict itself (p.6 "higher invasiveness
rank wins" vs p.13 "the last plant to spread in wins").  Three readings:

  rank       both empty and occupied cells go to the highest invasiveness rank
  last_wins  every contested cell goes to the last spreader, occupied or not
  hybrid     empty cell -> last spreader (neither seedling is mature, so rank
             cannot apply); occupied cell -> strictly higher rank displaces

Runs one identical schedule under all three and prints final coverage and the
per-species cell counts, so the size of the modelling risk is a number rather
than an argument.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.sim_schedules import LEVEL1_SPECIES, banded_schedule
from src.sim import COMPETITION_MODES, Rules, coverage, simulate, species_counts
from src.world import load_plants, load_world

LEVEL = sys.argv[1] if len(sys.argv) > 1 else "resources-docs/1(1).json"
DATASET = "resources-docs/plant_dataset.json"


def main() -> None:
    world = load_world(LEVEL)
    plants = load_plants(DATASET)
    sched = banded_schedule(world)

    names = {i: plants[i].name for i in LEVEL1_SPECIES}
    ranks = {i: plants[i].invasiveness_rank for i in LEVEL1_SPECIES}

    print("species (index, rank):",
          ", ".join(f"{names[i]}={i}/r{ranks[i]}" for i in LEVEL1_SPECIES))
    print()

    results = {}
    for mode in COMPETITION_MODES:
        st = simulate(world, plants, sched, Rules(competition=mode))
        results[mode] = (coverage(st), species_counts(st))

    header = f"{'mode':<10} {'coverage':>9} " + "".join(
        f"{names[i][:9]:>10}" for i in LEVEL1_SPECIES)
    print(header)
    print("-" * len(header))
    for mode in COMPETITION_MODES:
        cov, counts = results[mode]
        row = f"{mode:<10} {cov:>9} " + "".join(
            f"{counts.get(i, 0):>10}" for i in LEVEL1_SPECIES)
        print(row)

    print()
    base = results["hybrid"][1]
    for mode in ("rank", "last_wins"):
        cov_d = results[mode][0] - results["hybrid"][0]
        per = {i: results[mode][1].get(i, 0) - base.get(i, 0)
               for i in LEVEL1_SPECIES}
        print(f"{mode:>10} vs hybrid: coverage {cov_d:+d}, per-species "
              + ", ".join(f"{names[i]} {per[i]:+d}" for i in LEVEL1_SPECIES))


def head_to_head(world, plants, a: int, b: int, ticks: int = 90):
    """Two species seeded at opposite ends of the open dirt band (rows 20-29).

    Whoever owns the collision front answers the real question: does rank
    govern pushing into an occupied cell, or does arrival order?
    """
    from src.sim import make_schedule
    sched = make_schedule([(0, a, 24, 8), (0, b, 24, 41)])
    out = {}
    for mode in COMPETITION_MODES:
        st = simulate(world, plants, sched, Rules(competition=mode),
                      n_ticks=ticks, species=(a, b))
        c = species_counts(st)
        out[mode] = (c.get(a, 0), c.get(b, 0))
    return out


def pairs_section(world, plants) -> None:
    names = {i: plants[i].name for i in LEVEL1_SPECIES}
    print()
    print("head-to-head, 90 ticks, seeded at (24,8) and (24,41) "
          "[cells owned by A / by B]")
    hdr = f"{'A vs B':<28}" + "".join(f"{m:>18}" for m in COMPETITION_MODES)
    print(hdr)
    print("-" * len(hdr))
    for i, a in enumerate(LEVEL1_SPECIES):
        for b in LEVEL1_SPECIES[i + 1:]:
            res = head_to_head(world, plants, a, b)
            label = f"{names[a]} vs {names[b]}"
            print(f"{label:<28}" + "".join(
                f"{res[m][0]:>8} /{res[m][1]:>8}" for m in COMPETITION_MODES))


if __name__ == "__main__":
    main()
    pairs_section(load_world(LEVEL), load_plants(DATASET))
