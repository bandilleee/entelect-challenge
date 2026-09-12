"""Runtime + determinism measurement for the simulator.

    python experiments/sim_bench.py "resources-docs/1(1).json"

Reports the wall-clock cost of a full 500-tick / ~2000-placement rollout and
the SHA-256 of ``FinalState.to_dict()`` so the same rollout can be compared
across processes with different ``PYTHONHASHSEED``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.sim_schedules import banded_schedule
from src.sim import Rules, coverage, simulate, species_counts
from src.world import load_plants, load_world

LEVEL = sys.argv[1] if len(sys.argv) > 1 else "resources-docs/1(1).json"
DATASET = "resources-docs/plant_dataset.json"
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 7


def digest(state) -> str:
    blob = json.dumps(state.to_dict(), sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    world = load_world(LEVEL)
    plants = load_plants(DATASET)
    sched = banded_schedule(world)
    n = sum(len(a["plants"]) for a in sched["actions"])
    rules = Rules()

    state = simulate(world, plants, sched, rules)  # warm-up / import cost
    times = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        state = simulate(world, plants, sched, rules)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()

    print(f"level      : {LEVEL}")
    print(f"grid       : {world.rows}x{world.cols}  ticks={world.ticks}")
    print(f"placements : {n}")
    print(f"competition: {rules.competition}")
    print(f"runtime ms : best={times[0]:.1f} median={times[len(times)//2]:.1f} "
          f"worst={times[-1]:.1f}  (n={REPS})")
    print(f"coverage   : {coverage(state)} / {world.rows * world.cols}")
    print(f"counts     : {species_counts(state)}")
    print(f"sha256     : {digest(state)}")


if __name__ == "__main__":
    main()
