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

# Level 1 unlocked species, ordered by invasiveness_rank ASCENDING, then by
# time_to_maturity DESCENDING (a faster-maturing plant is the bigger threat
# over any given window, so it is placed later and gets less time to act).
#
#   index  name              rank  maturity  spread_rate
#   1      Grass              1      1          2
#   2      Rose Bush          2     10          2
#   6      Lavender           2      4          3
#   5      Dwarf Sunflower    4      5          4
#   12     Oak Tree          10     20          7
PLACEMENT_ORDER = [1, 2, 6, 5, 12]

# Per-species placement window (first_tick, last_tick), 20 placements per tick.
# 18 ticks x 20 = 360 cells each = 1800 = every usable cell on the Level 1 map.
#
# Two constraints set these windows:
#   - Nutrients. A cell holds 100 and drains 1/tick, so a plant placed at tick
#     t is still alive at tick 500 only if t > 400. Everything starts at 401.
#   - Invasiveness. A plant that matures can push into an occupied neighbour,
#     so the most invasive species are placed last and given least time. Oak
#     starts at 481: maturity 20 means it matures at 501+, i.e. never within
#     the scored run. It casts no shade, never spreads and displaces nothing,
#     but still counts toward both species entropy and coverage.
#
# These are the optimiser's main knobs. Keep them here, not inline.
WINDOWS = {
    1:  (401, 418),   # Grass           rank 1, displaces nothing
    2:  (419, 436),   # Rose Bush       rank 2
    6:  (437, 454),   # Lavender        rank 2, matures faster than Rose
    5:  (455, 472),   # Dwarf Sunflower rank 4, top active displacer
    12: (481, 498),   # Oak Tree        rank 10, inert by construction
}

PER_TICK_CAP = 20


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


def partition(cells, n_regions):
    """Split `cells` into `n_regions` compact, connected regions of equal size.

    Compactness is the point: a species surrounded by its own kind has contested
    edges only on its perimeter, so the fewer and shorter those borders, the
    less a maturing neighbour can displace. Every usable cell on this map is one
    connected component even under Von Neumann adjacency, so there is no
    geographic quarantine available and this is the next best thing.

    Regions are grown one at a time, each taking exactly `target` cells by BFS
    from the most remote remaining cell. Growing sequentially rather than
    concurrently guarantees the exact sizes the entropy term wants, and equal
    sizes matter more than perfectly even borders. Fully deterministic: every
    candidate list is sorted before a choice is made.
    """
    order = sorted(cells)
    remaining = set(order)
    target = len(cells) // n_regions
    regions = []

    def neighbours(cell):
        r, c = cell
        return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))

    for region_i in range(n_regions):
        pool = sorted(remaining)
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

    regions = partition(cells, len(PLACEMENT_ORDER))
    border = isolation_scores(regions)

    # Most invasive species -> most self-contained region, as insurance in case
    # the "Oak never matures" timing assumption is off by a tick.
    by_isolation = sorted(range(len(regions)), key=lambda i: (border[i], i))
    by_threat = sorted(
        PLACEMENT_ORDER,
        key=lambda idx: (-plants[idx]["growth"]["invasiveness_rank"], idx),
    )
    assignment = {sp: by_isolation[n] for n, sp in enumerate(by_threat)}

    # tick -> list of placements, built in PLACEMENT_ORDER so the per-tick cap
    # is never contested between species.
    by_tick = {}
    for species in PLACEMENT_ORDER:
        first, last = WINDOWS[species]
        region = regions[assignment[species]]
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
