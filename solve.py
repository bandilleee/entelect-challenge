#!/usr/bin/env python3
"""Entry point: level file -> planting schedule.

Usage: python solve.py --input <level>.json --output <schedule>.json

Platform rule 6 requires deterministic, reproducible solutions: the same input
must produce a byte-identical output every run, on their machine as well as
ours. There is deliberately no RNG in here, and every iteration over a set is
sorted first (PYTHONHASHSEED is not stable across processes).
"""
import argparse, json, pathlib, sys, time
from collections import deque


def load(path):
    text = pathlib.Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ============================ REPLACE FROM HERE ============================
DATA = pathlib.Path(__file__).parent / "resources-docs"

# Level 1 unlocked species, in placement order (earliest window first).
#
#   index  name              rank  maturity  spread_rate
#   1      Grass              1      1          2
#   2      Rose Bush          2     10          2
#   6      Lavender           2      4          3
#   5      Dwarf Sunflower    4      5          4
#   12     Oak Tree          10     20          7
#
# This order is measured, not reasoned. The first version of this file ordered
# by ascending invasiveness_rank on the theory that the most aggressive species
# should get the least time to displace a neighbour. Sweeping all 120
# orderings through the simulator across the whole rule matrix killed that
# theory: what actually matters is EXPOSURE TIME, not rank. The species planted
# earliest has the most ticks to spread, so the question is which species does
# the most damage per tick of exposure -- and that is Grass, which matures in a
# single tick, despite having the LOWEST invasiveness rank in the catalogue.
#
# Every one of the top 10 orderings plants Grass last; every one of the bottom
# three plants it first or second. Worst case across the rule matrix went from
# 0.0023 (rank order) to 0.1073 (this order), a 47x improvement, and mean from
# 0.1985 to 0.2392. Reproduce with:
#     python experiments/sweep_order.py 'resources-docs/1(1).json' --full
PLACEMENT_ORDER = [12, 2, 6, 5, 1]

# Placement span. Nutrients set the start: a cell holds 100 and drains 1/tick,
# so a plant placed at tick t is alive at tick 500 only if t > 400. Nothing is
# placed before 401, and the last placement lands at 498.
#
# Each species gets a consecutive block of ticks inside this span, sized to its
# seed count, handed out in PLACEMENT_ORDER and packed against the END of the
# span. Packing late matters: every tick a species is in the ground before 500
# is a tick it can spread, so the whole schedule is pushed as late as the
# 20-per-tick cap allows.
FIRST_TICK = 401
LAST_TICK = 498

PER_TICK_CAP = 20

# How many cells each species is SEEDED with, as a share of the usable area.
#
# Equal shares are the wrong target. The entropy term wants the five species
# equal at tick 500, but between planting and scoring they spread into and over
# each other at very different rates, so equal seeding does not produce an equal
# finish. Sunflower roughly doubles its area; Rose Bush loses most of its own.
#
# These weights pre-compensate for that drift: each species is seeded in inverse
# proportion to how much it gains. They are fitted against the simulator by a
# deterministic feedback loop, over the whole rule matrix rather than one
# reading, so they are a compromise across the readings rather than tuned to a
# guess. Refit with:
#     python experiments/fit_seeds.py 'resources-docs/1(1).json'
#
# Solving itself stays simulation-free and fast, which keeps solve.py trivially
# reproducible under platform rule 6.
SEED_WEIGHTS = {
    12: 0.126,   # Oak Tree         matures and spreads; needs fewer seeds
    2:  0.227,   # Rose Bush        loses ground; needs more
    6:  0.307,   # Lavender         loses the most; needs the most
    5:  0.144,   # Dwarf Sunflower  roughly doubles its area; needs fewest
    1:  0.195,   # Grass            planted last, so close to break-even
}


def seed_counts(total):
    """Integer seed counts per species, summing to exactly `total`.

    Largest-remainder apportionment, ties broken by plant index so the result
    does not depend on dict or float ordering.
    """
    raw = {s: SEED_WEIGHTS[s] * total for s in PLACEMENT_ORDER}
    counts = {s: int(raw[s]) for s in PLACEMENT_ORDER}
    short = total - sum(counts.values())
    for s in sorted(PLACEMENT_ORDER, key=lambda x: (-(raw[x] - counts[x]), x)):
        if short <= 0:
            break
        counts[s] += 1
        short -= 1
    return counts


def tick_windows(sizes):
    """Consecutive tick block per species, sized to its seed count.

    Blocks are laid out in PLACEMENT_ORDER and packed against LAST_TICK, so the
    species planted last finishes as close to scoring as possible. Raises if the
    span cannot hold the requested cells at the per-tick cap, rather than
    silently dropping placements.
    """
    needed = {s: -(-sizes[s] // PER_TICK_CAP) for s in PLACEMENT_ORDER}
    total = sum(needed.values())
    start = LAST_TICK + 1 - total
    if start < FIRST_TICK:
        raise ValueError(
            f"{sum(sizes.values())} cells need {total} ticks; span "
            f"{FIRST_TICK}..{LAST_TICK} holds {LAST_TICK - FIRST_TICK + 1}"
        )
    windows, tick = {}, start
    for species in PLACEMENT_ORDER:
        windows[species] = (tick, tick + needed[species] - 1)
        tick += needed[species]
    return windows


def load_plants():
    """Plant catalogue keyed by index."""
    plants = json.loads((DATA / "plant_dataset.json").read_text())
    return {p["index"]: p for p in plants}


def build_grid(world):
    """terrain and soil arrays. Cells absent from `cells` default to (0, 0)."""
    rows, cols = world["rows"], world["cols"]
    terrain = [[0] * cols for _ in range(rows)]
    soil = [[0] * cols for _ in range(rows)]
    for c in world["cells"]:
        terrain[c["row"]][c["col"]] = c["terrain"]
        soil[c["row"]][c["col"]] = c["soil"]
    return terrain, soil


def usable_cells(world, terrain, soil, preferred):
    """Cells any of our species can occupy: terrain 0 and an allowed soil.

    On Level 1 all five species share preferred_soil [0, 1], so clay (soil 2)
    is dead space and this is a single set of 1800 cells.
    """
    allowed = set(preferred)
    return [
        (r, c)
        for r in range(world["rows"])
        for c in range(world["cols"])
        if terrain[r][c] == 0 and soil[r][c] in allowed
    ]


def partition(cells, sizes):
    """Split `cells` into compact, connected regions of the given `sizes`.

    Compactness is the point: a species surrounded by its own kind has contested
    edges only on its perimeter, so the fewer and shorter those borders, the
    less a maturing neighbour can displace. Every usable cell on this map is one
    connected component even under Von Neumann adjacency, so there is no
    geographic quarantine available and this is the next best thing.

    Regions are grown one at a time, each taking exactly `sizes[i]` cells by BFS
    from the most remote remaining cell. Growing sequentially rather than
    concurrently guarantees exact sizes, and exact sizes are what the entropy
    term is built on. Fully deterministic: every candidate list is sorted before
    a choice is made.
    """
    order = sorted(cells)
    remaining = set(order)
    n_regions = len(sizes)
    regions = []

    def neighbours(cell):
        r, c = cell
        return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))

    for region_i in range(n_regions):
        pool = sorted(remaining)
        target = sizes[region_i]
        if region_i == n_regions - 1:
            regions.append(pool)       # last region takes the remainder
            break

        # Seed at the most remote remaining cell: the one furthest (by hop
        # distance through what is left) from everything already taken. With
        # nothing taken yet, that is simply the first cell in sorted order.
        taken = [c for c in order if c not in remaining]
        if taken:
            dist = {c: 0 for c in taken}
            q = deque(taken)
            while q:
                cur = q.popleft()
                for nxt in neighbours(cur):
                    if nxt in remaining and nxt not in dist:
                        dist[nxt] = dist[cur] + 1
                        q.append(nxt)
            seed = max(pool, key=lambda c: (dist.get(c, 10 ** 9), c))
        else:
            seed = pool[0]

        grabbed = [seed]
        seen = {seed}
        q = deque([seed])
        while q and len(grabbed) < target:
            cur = q.popleft()
            for nxt in sorted(neighbours(cur)):
                if len(grabbed) >= target:
                    break
                if nxt in remaining and nxt not in seen:
                    seen.add(nxt)
                    grabbed.append(nxt)
                    q.append(nxt)
        # If BFS stranded (a disconnected remainder), top up in sorted order.
        if len(grabbed) < target:
            for cell in pool:
                if len(grabbed) >= target:
                    break
                if cell not in seen:
                    seen.add(cell)
                    grabbed.append(cell)

        remaining -= seen
        regions.append(sorted(grabbed))

    return regions


def isolation_scores(regions):
    """Per region, the count of its cells that border a different region.

    The region with the fewest such cells is the most self-contained, and is
    where we put the species we least want leaking.
    """
    owner = {}
    for i, cells in enumerate(regions):
        for cell in cells:
            owner[cell] = i
    out = []
    for i, cells in enumerate(regions):
        border = sum(
            1 for (r, c) in cells
            if any(owner.get((r + dr, c + dc), i) != i
                   for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)))
        )
        out.append(border)
    return out


def solve(world, level=None):
    """Balanced five-species fill of every usable cell.

    Level 1 unlocks exactly five species and nothing else ever unlocks, so the
    score is entropy (maximised at equal proportions) times coverage, plus a
    longevity term. Every usable cell gets an explicit placement, which pins
    coverage near its 0.72 ceiling; the species split is what the tick windows
    above are protecting.
    """
    plants = load_plants()
    terrain, soil = build_grid(world)
    preferred = plants[PLACEMENT_ORDER[0]]["preferred_soil"]
    cells = usable_cells(world, terrain, soil, preferred)

    sizes = seed_counts(len(cells))
    regions = partition(cells, [sizes[s] for s in PLACEMENT_ORDER])
    windows = tick_windows(sizes)

    # tick -> list of placements, built in PLACEMENT_ORDER so the per-tick cap
    # is never contested between species.
    by_tick = {}
    for region_i, species in enumerate(PLACEMENT_ORDER):
        first, last = windows[species]
        region = regions[region_i]
        tick = first
        for n, (r, c) in enumerate(region):
            tick = first + n // PER_TICK_CAP
            if tick > last:
                break
            by_tick.setdefault(tick, []).append(
                {"plant_index": species, "row": r, "col": c}
            )

    actions = [{"tick": t, "plants": by_tick[t]} for t in sorted(by_tick)]
    return {"actions": actions}
# ============================= TO HERE =====================================


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--level", default=None)
    a = p.parse_args()
    t0 = time.time()
    answer = solve(load(a.input), a.level)
    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(answer, indent=2))
    n = sum(len(x["plants"]) for x in answer["actions"])
    print(f"solved in {time.time()-t0:.3f}s -> {out} "
          f"({n} placements over {len(answer['actions'])} ticks)", file=sys.stderr)


if __name__ == "__main__":
    main()
