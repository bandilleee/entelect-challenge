#!/usr/bin/env python3
"""Entry point: level file -> planting schedule.

Usage: python solve.py --input <level>.json --output <schedule>.json

Platform rule 6 requires deterministic, reproducible solutions: the same input
must produce a byte-identical output every run, on their machine as well as
ours. There is deliberately no RNG in here, and every iteration over a set is
sorted first (PYTHONHASHSEED is not stable across processes).

Two solvers live behind one CLI, chosen from the WORLD FILE rather than the
filename:

  * a no-animals, seasons-only level has a five-species fixed point and no
    unlock puzzle at all -- that is the Level 1 solver, unchanged, and it is
    the configuration that actually scored 274,709,453;
  * anything with animals or events can walk the unlock graph, and species
    count (H = log_31(S)) dominates everything else in the score, so that
    solver spends the first 400 ticks on disposable scaffolding and the last
    99 on the scoring garden.
"""
import argparse, json, pathlib, sys, time
from collections import deque

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from src import plan as planner


def load(path):
    text = pathlib.Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ============================ REPLACE FROM HERE ============================
DATA = pathlib.Path(__file__).parent / "resources-docs"

PER_TICK_CAP = 20

# ---------------------------------------------------------------------------
# LEVEL 1 -- five species, no unlock puzzle. Do not touch without a submission.
# ---------------------------------------------------------------------------
#
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
# Reproduce with:
#     python experiments/sweep_order.py 'resources-docs/1(1).json' --full
PLACEMENT_ORDER = [12, 2, 6, 5, 1]

# Placement span. Nutrients set the start: a cell holds 100 and drains 1/tick,
# so a plant placed at tick t is alive at tick 500 only if t > 400.
FIRST_TICK = 401
LAST_TICK = 498

# How many cells each species is SEEDED with, as a share of the usable area.
#
# THREE SUBMISSIONS SETTLED THIS. Equal seeding is the obvious target -- the
# entropy term is maximised at equal proportions -- and it is wrong:
#
#   # | placed (Grass/Rose/Sunf/Lav/Oak) | ticks   | tail | final H | score
#   1 | 351 / 409 / 260 / 553 / 227      | 407-498 |  2   | 0.4531  | 274,709,453
#   2 | 360 / 360 / 360 / 360 / 360      | 401-490 | 10   | 0.3400  | 209,170,416
#   3 | 360 / 360 / 360 / 360 / 360      | 410-499 |  1   | ~0.373  | 228,005,785
#
# Submission 3 had a SHORTER tail than submission 1 and still lost 46M, so the
# tail is not the whole story. The thing submission 1 uniquely had was small
# territories for the two aggressive species -- Oak 227 and Sunflower 260
# against 360 each in the others. Territory size sets the length of a species'
# spread frontier, so giving Oak and Sunflower less ground is what limited
# their expansion. These weights are not pre-compensating for phantom drift;
# they are buying stability, and removing them cost 46M.
#
# Refit (against the simulator, which is the weaker evidence) with:
#     python experiments/fit_seeds.py 'resources-docs/1(1).json'
SEED_WEIGHTS = {
    12: 0.126,   # Oak Tree         aggressive: smallest territory
    2:  0.227,   # Rose Bush
    6:  0.307,   # Lavender         passive: largest territory
    5:  0.144,   # Dwarf Sunflower  aggressive: small territory
    1:  0.195,   # Grass
}


def seed_counts(total, order=None, weights=None):
    """Integer seed counts per species, summing to exactly `total`.

    Largest-remainder apportionment, ties broken by plant index so the result
    does not depend on dict or float ordering.
    """
    order = order or PLACEMENT_ORDER
    weights = weights or SEED_WEIGHTS
    raw = {s: weights[s] * total for s in order}
    counts = {s: int(raw[s]) for s in order}
    short = total - sum(counts.values())
    for s in sorted(order, key=lambda x: (-(raw[x] - counts[x]), x)):
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
    if total > LAST_TICK - FIRST_TICK + 1:
        raise ValueError(
            f"{sum(sizes.values())} cells need {total} ticks; span "
            f"{FIRST_TICK}..{LAST_TICK} holds {LAST_TICK - FIRST_TICK + 1}"
        )
    # Packed hard against the END of the span. Any tick left between the LAST
    # placement and scoring is a tick in which mature plants spread and
    # overwrite lower-ranked neighbours, strictly by invasiveness_rank:
    #
    #     last placement 498 -> 2-tick tail ->  10 cells moved -> 274,709,453
    #     last placement 490 -> 10-tick tail -> 791 cells moved -> 209,170,416
    start = LAST_TICK + 1 - total
    windows, tick = {}, start
    for species in PLACEMENT_ORDER:
        windows[species] = (tick, tick + needed[species] - 1)
        tick += needed[species]
    return windows


# ---------------------------------------------------------------------------
# shared grid helpers
# ---------------------------------------------------------------------------


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
    """Cells any of our species can occupy: terrain 0 and an allowed soil."""
    allowed = set(preferred)
    return [
        (r, c)
        for r in range(world["rows"])
        for c in range(world["cols"])
        if terrain[r][c] == 0 and soil[r][c] in allowed
    ]


def _neighbours4(cell):
    r, c = cell
    return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))


def partition(cells, sizes):
    """Split `cells` into compact, connected regions of the given `sizes`.

    Compactness is the point: a species surrounded by its own kind has contested
    edges only on its perimeter, so the fewer and shorter those borders, the
    less a maturing neighbour can displace. Fully deterministic: every candidate
    list is sorted before a choice is made.
    """
    order = sorted(cells)
    remaining = set(order)
    n_regions = len(sizes)
    regions = []

    for region_i in range(n_regions):
        pool = sorted(remaining)
        target = sizes[region_i]
        if region_i == n_regions - 1:
            regions.append(pool)       # last region takes the remainder
            break

        # Seed at the most remote remaining cell: the one furthest (by hop
        # distance through what is left) from everything already taken.
        taken = [c for c in order if c not in remaining]
        if taken:
            dist = {c: 0 for c in taken}
            q = deque(taken)
            while q:
                cur = q.popleft()
                for nxt in _neighbours4(cur):
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
            for nxt in sorted(_neighbours4(cur)):
                if len(grabbed) >= target:
                    break
                if nxt in remaining and nxt not in seen:
                    seen.add(nxt)
                    grabbed.append(nxt)
                    q.append(nxt)
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


def grow_block(available, count, seed=None):
    """Claim `count` compact cells out of the sorted set `available`.

    BFS from a seed, falling back to sorted order when the frontier strands on
    a disconnected remainder. Returns the claimed cells; the caller removes
    them from `available`.
    """
    if count <= 0 or not available:
        return []
    pool = sorted(available)
    start = seed if seed in available else pool[0]
    grabbed, seen, q = [start], {start}, deque([start])
    while q and len(grabbed) < count:
        cur = q.popleft()
        for nxt in sorted(_neighbours4(cur)):
            if len(grabbed) >= count:
                break
            if nxt in available and nxt not in seen:
                seen.add(nxt)
                grabbed.append(nxt)
                q.append(nxt)
    if len(grabbed) < count:
        for cell in pool:
            if len(grabbed) >= count:
                break
            if cell not in seen:
                seen.add(cell)
                grabbed.append(cell)
    return sorted(grabbed)


# ---------------------------------------------------------------------------
# LEVEL 2 -- scaffolding then garden
# ---------------------------------------------------------------------------

# Nutrients: a virgin cell holds 100 and drains 1/tick, so nothing planted at or
# before tick 400 is alive when the engine scores tick 500. The scoring garden
# therefore lives entirely inside [401, 499] and finishes on the last legal
# tick, leaving a one-tick tail for redistribution.
GARDEN_FIRST_TICK = 401
GARDEN_LAST_TICK = 499
NUTRIENT_LIFETIME = 100

# Scaffolding may re-use a garden cell only if that use finishes early enough
# for the cell to die AND regenerate to full before the garden is planted:
# planted at t, dead at t+100, back to 100 nutrients at t+200. With the garden
# starting at 401 that means t <= 201.
GARDEN_LOCK_TICK = GARDEN_FIRST_TICK - 2 * NUTRIENT_LIFETIME

# Trees need to be mature before anything with `shade_required` is planted
# under them, so a stage carrying shade-dependent plants is padded to at least
# this many ticks and plants its trees first.
TREE_MATURITY = 20
SHADE_STAGE_MIN_TICKS = TREE_MATURITY + 5
SHADE_RADIUS = 4                     # Oak Tree's shade_radius
SHADE_LATTICE = 6                    # stride: every cell is within 3 of a tree

OAK = 12


def rules_of(plant):
    out = set()
    for r in plant["rules"].get("weaknesses", []):
        out.add(r["type"])
    for r in plant["rules"].get("special", []):
        out.add(r["type"])
    return out


def stripe(cells):
    """Every other row. Keeps `die_if_neighbors_greater_than` cells at two
    Moore neighbours instead of eight -- Blue Moss is the one that cares, and
    it gates Silver Fern, Moonpetal Lily, Mire Bloom and Purple Canopy Tree."""
    return [c for c in cells if c[0] % 2 == 0]


def lattice(cells, stride=2):
    """Every `stride`-th cell in both axes, so nothing is orthogonally or
    diagonally adjacent. Living Topiary's `no_adjacent_plants` wants this."""
    return [c for c in cells if c[0] % stride == 0 and c[1] % stride == 0]


PATTERNS = {
    "die_if_neighbors_greater_than": (stripe, 2.2),
    "no_adjacent_plants": (lambda cs: lattice(cs, 2), 4.4),
}


def pattern_for(plant):
    for rule, (fn, blow_up) in sorted(PATTERNS.items()):
        if rule in rules_of(plant):
            return fn, blow_up
    return (lambda cs: list(cs)), 1.0


def chebyshev_cover(centres, radius, rows, cols):
    out = set()
    for (r, c) in sorted(centres):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    out.add((rr, cc))
    return out


def adjacent_to_terrain(terrain, rows, cols, kind):
    out = set()
    for r in range(rows):
        for c in range(cols):
            if terrain[r][c] != kind:
                continue
            for (rr, cc) in _neighbours4((r, c)):
                if 0 <= rr < rows and 0 <= cc < cols and terrain[rr][cc] == 0:
                    out.add((rr, cc))
    return out


def apportion(total, keys, caps):
    """Split `total` as equally as possible across `keys`, respecting `caps`.

    Entropy is maximised at equal proportions, so the target is equality; a
    species whose terrain caps it below its share hands the remainder back and
    the rest split it again. Deterministic water-filling, ties by key order.
    """
    out = {k: 0 for k in keys}
    live = [k for k in keys if caps.get(k, 0) > 0]
    left = total
    while left > 0 and live:
        share = left // len(live)
        if share == 0:
            for k in live:
                if left <= 0:
                    break
                if out[k] < caps[k]:
                    out[k] += 1
                    left -= 1
            break
        progressed = False
        for k in list(live):
            take = min(share, caps[k] - out[k])
            if take > 0:
                out[k] += take
                left -= take
                progressed = True
            if out[k] >= caps[k]:
                live.remove(k)
        if not progressed:
            break
    return out


class Land:
    """Who owns which cell, and when a cell last died.

    A cell planted at tick t dies at t + 100 and then regenerates 1 nutrient
    per tick, so re-planting it at tick u leaves the new plant (u - death)
    nutrients -- it must therefore be at least as many as the ticks the new
    plant has to survive. That single rule is what keeps the scaffolding from
    quietly poisoning its own thresholds.
    """

    def __init__(self, cells):
        self.free = set(cells)
        self.death = {}

    def available(self, at_tick, survive):
        return {c for c in self.free
                if c not in self.death or at_tick - self.death[c] >= survive}

    def take(self, cells, tick):
        for c in cells:
            self.death[c] = tick + NUTRIENT_LIFETIME


def solve_level2(world, plants):
    rows, cols = world["rows"], world["cols"]
    terrain, soil = build_grid(world)
    total_cells = rows * cols

    stages, state = planner.unlock_stages(world)
    placeable, _ = planner.placeable_species(
        world, sorted({soil[r][c] for r in range(rows) for c in range(cols)
                       if terrain[r][c] == 0}))
    garden_order = [idx for idx, _ in placeable]           # dependency order
    idx_of = {name: i for name, i in state.index.items()}

    soil_ok = {i: set(plants[i]["preferred_soil"]) for i in plants}

    def cells_for_plant(idx):
        return {(r, c) for r in range(rows) for c in range(cols)
                if terrain[r][c] == 0 and soil[r][c] in soil_ok[idx]}

    all_usable = {(r, c) for r in range(rows) for c in range(cols)
                  if terrain[r][c] == 0 and soil[r][c] in (0, 1)}
    clay = {(r, c) for r in range(rows) for c in range(cols)
            if terrain[r][c] == 0 and soil[r][c] == 2}
    near_stone = adjacent_to_terrain(terrain, rows, cols, 2)
    near_water = adjacent_to_terrain(terrain, rows, cols, 1)

    # ---- reserve the garden -------------------------------------------------
    # Bottom-up band, plus every stone-adjacent cell wherever it lies (Stone
    # Reed's `must_be_adjacent_to: rock_or_path` has nowhere else to go). Clay
    # is garden by construction: no scaffolding species can use it, and Mire
    # Bloom is the only plant in the catalogue whose preferred_soil includes it.
    garden_budget = (GARDEN_LAST_TICK - GARDEN_FIRST_TICK + 1) * PER_TICK_CAP
    garden_target = int(garden_budget * 1.35)
    band = sorted(all_usable, key=lambda rc: (-rc[0], rc[1]))[:garden_target]
    garden_pool = set(band) | (near_stone & all_usable) | clay
    scaffold_pool = all_usable - garden_pool

    # ---- phase A: scaffolding ----------------------------------------------
    land_scaffold = Land(scaffold_pool)
    land_garden_early = Land(garden_pool & all_usable)
    phase_a = []                      # (tick, plant_index, row, col)
    death_ticks = []                  # ascending, for the dead-matter gate
    cursor, gate_dead = 0, 0
    warnings = []

    for si, stage in enumerate(stages, 1):
        grow = stage["grow"]
        if not grow:
            continue
        shade_plants = [p for p in sorted(grow)
                        if "shade_required" in rules_of(plants[idx_of[p]])]
        blow = {}
        for p in sorted(grow):
            _, factor = pattern_for(plants[idx_of[p]])
            blow[p] = factor
        # tick budget: patterned species need more ground than placements
        placements = sum(grow.values())
        length = max(-(-placements // PER_TICK_CAP), 1)
        if shade_plants:
            length = max(length, SHADE_STAGE_MIN_TICKS)

        start = max(cursor, stage["after_tick"], gate_dead)
        end = start + length - 1
        may_use_garden = end <= GARDEN_LOCK_TICK

        def claim(plant_name, n_cells, area):
            """Ground for one species this stage, garden pool first while it is
            still safe to borrow it, so the scaffolding-only land survives for
            the later stages that cannot give it back in time."""
            pools = []
            if may_use_garden:
                pools.append(land_garden_early)
            pools.append(land_scaffold)
            got = []
            for land in pools:
                if len(got) >= area:
                    break
                avail = land.available(start, length)
                block = grow_block(avail, area - len(got))
                for c in block:
                    land.free.discard(c)
                land.take(block, start)
                got.extend(block)
            if len(got) < n_cells:
                warnings.append(
                    f"stage {si}: {plant_name} wanted {n_cells} cells, "
                    f"got {len(got)} -- threshold may not fire")
            return sorted(got)

        trees, ordinary, shaded = [], [], []
        for p in sorted(grow, key=lambda p: (idx_of[p], p)):
            n = grow[p]
            pat_fn, _ = pattern_for(plants[idx_of[p]])
            area = int(-(-n * blow[p] // 1))
            block = claim(p, n, area)
            usable_block = pat_fn(block)
            if len(usable_block) < n and len(block) >= n:
                usable_block = block[:n]         # pattern too lossy; go solid
            cells = usable_block[:n]
            entry = (idx_of[p], cells)
            if p in shade_plants:
                # every shaded cell needs a tree within SHADE_RADIUS
                oaks = [c for c in cells
                        if c[0] % SHADE_LATTICE == 0 and c[1] % SHADE_LATTICE == 0]
                shaded.append((idx_of[p], [c for c in cells if c not in set(oaks)]))
                trees.append((OAK, oaks))
            elif "shade_radius" in rules_of(plants[idx_of[p]]):
                trees.append(entry)
            else:
                ordinary.append(entry)

        emitted = []
        for group in (trees, ordinary, shaded):
            for pidx, cells in group:
                for c in cells:
                    emitted.append((pidx, c))
        # trees first and shade-dependants last, but the stage is padded to at
        # least SHADE_STAGE_MIN_TICKS so the trees are mature by then
        tick = start
        for i, (pidx, (r, c)) in enumerate(emitted):
            tick = start + i // PER_TICK_CAP
            phase_a.append((tick, pidx, r, c))
            death_ticks.append(tick + NUTRIENT_LIFETIME)
        cursor = max(end, tick) + 1

        need_dead = stage["dead_cells"]
        if need_dead:
            ds = sorted(death_ticks)
            gate_dead = (ds[need_dead - 1] + 1) if len(ds) >= need_dead else cursor
        else:
            gate_dead = 0

    if cursor > GARDEN_FIRST_TICK:
        warnings.append(
            f"scaffolding runs to tick {cursor - 1}, past the garden's "
            f"{GARDEN_FIRST_TICK} start")

    # ---- phase B: the scoring garden ---------------------------------------
    # 20 placements/tick over [401, 499] is 1980 cells against 6135 usable, so
    # unlike Level 1 we cannot fill the board. Coverage is therefore whatever
    # the budget buys, and the lever worth having is S: H = log_31(S), and at
    # this coverage one more species is worth far more than one more cell.
    garden_free = set(garden_pool)
    claimed = {}

    def garden_claim(idx, n, allowed, seed=None):
        pat_fn, blow = pattern_for(plants[idx])
        area = int(-(-n * blow // 1))
        pool = garden_free & allowed
        block = grow_block(pool, area, seed)
        cells = pat_fn(block)
        if len(cells) < n and len(block) >= n:
            cells = block[:n]
        cells = sorted(cells)[:n]
        # the whole block leaves the pool, not just the cells we plant: the
        # gaps are what make the pattern work
        for c in block:
            garden_free.discard(c)
        return cells

    # caps: terrain-constrained species first, so the unconstrained ones take
    # what is left rather than squatting on the only ground that works.
    caps = {}
    for idx in garden_order:
        pool = cells_for_plant(idx) & garden_pool
        rules = rules_of(plants[idx])
        if "must_be_adjacent_to" in rules:
            feature = next(r for r in plants[idx]["rules"]["weaknesses"]
                           if r["type"] == "must_be_adjacent_to")["feature"]
            pool &= near_water if feature == "water" else near_stone
        _, blow = pattern_for(plants[idx])
        caps[idx] = int(len(pool) / blow)
    targets = apportion(garden_budget, garden_order, caps)

    constrained, shade_needing, free_species = [], [], []
    for idx in garden_order:
        rules = rules_of(plants[idx])
        if "must_be_adjacent_to" in rules:
            constrained.append(idx)
        elif "shade_required" in rules:
            shade_needing.append(idx)
        else:
            free_species.append(idx)

    # 1. terrain-locked species
    for idx in constrained:
        feature = next(r for r in plants[idx]["rules"]["weaknesses"]
                       if r["type"] == "must_be_adjacent_to")["feature"]
        allowed = cells_for_plant(idx) & (near_water if feature == "water"
                                          else near_stone)
        claimed[idx] = garden_claim(idx, targets[idx], allowed)

    # 2. the shade providers, before the things that need shade
    shade_sources = [i for i in free_species
                     if "shade_radius" in rules_of(plants[i])]
    for idx in shade_sources:
        claimed[idx] = garden_claim(idx, targets[idx], cells_for_plant(idx))

    # 3. shade_required species, inside the trees' shadow
    shadow = chebyshev_cover(
        [c for i in shade_sources for c in claimed.get(i, [])],
        SHADE_RADIUS, rows, cols)
    for idx in shade_needing:
        got = garden_claim(idx, targets[idx], cells_for_plant(idx) & shadow)
        if len(got) < targets[idx]:
            warnings.append(f"{plants[idx]['plant']} got {len(got)}/"
                            f"{targets[idx]} shaded cells")
        claimed[idx] = got

    # 4. everything else; Grass last because `no_shade_survival` means it must
    #    stay out of the shadow entirely.
    rest = [i for i in free_species if i not in shade_sources]
    rest.sort(key=lambda i: ("no_shade_survival" in rules_of(plants[i]), i))
    for idx in rest:
        allowed = cells_for_plant(idx)
        if "no_shade_survival" in rules_of(plants[idx]):
            allowed = allowed - shadow
        claimed[idx] = garden_claim(idx, targets[idx], allowed)

    # ---- emit, in unlock-dependency order, finishing at tick 499 ------------
    # Dependency order is a hedge: we plan for latching unlocks, but if the
    # engine re-evaluates them live then a dependant placed before its
    # prerequisite is on the board would be silently dropped.
    ordered = []
    for idx in garden_order:
        for cell in claimed.get(idx, []):
            ordered.append((idx, cell))
    chunks = -(-len(ordered) // PER_TICK_CAP)
    first = GARDEN_LAST_TICK + 1 - chunks
    if first < GARDEN_FIRST_TICK:
        ordered = ordered[(chunks - (GARDEN_LAST_TICK - GARDEN_FIRST_TICK + 1))
                          * PER_TICK_CAP:]
        first = GARDEN_FIRST_TICK

    by_tick = {}
    for t, pidx, r, c in phase_a:
        by_tick.setdefault(t, []).append(
            {"plant_index": pidx, "row": r, "col": c})
    for i, (pidx, (r, c)) in enumerate(ordered):
        by_tick.setdefault(first + i // PER_TICK_CAP, []).append(
            {"plant_index": pidx, "row": r, "col": c})

    for w in warnings:
        print(f"  W {w}", file=sys.stderr)
    print(f"  phase A: {len(phase_a)} placements, ticks 0..{cursor - 1}",
          file=sys.stderr)
    print(f"  phase B: {len(ordered)} placements, ticks {first}.."
          f"{GARDEN_LAST_TICK}, {len([i for i in garden_order if claimed.get(i)])}"
          f" species", file=sys.stderr)
    return {"actions": [{"tick": t, "plants": by_tick[t]} for t in sorted(by_tick)]}


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def is_level1_shape(world):
    """Five-species fixed point: no animals, and nothing but season commands.

    Detected from the world file, never the filename. With animals disabled and
    no events, every first-tier unlock is gated behind an animal or an event, so
    the closure from the five starters is a fixed point at five and there is no
    unlock puzzle to solve.
    """
    if world.get("animals_enabled"):
        return False
    return all(str(c.get("type", "")).lower() == "season"
               for c in world.get("commands", []))


def solve(world, level=None):
    plants = load_plants()
    if not is_level1_shape(world):
        return solve_level2(world, plants)

    # Level 1: balanced five-species fill of every usable cell.
    terrain, soil = build_grid(world)
    preferred = plants[PLACEMENT_ORDER[0]]["preferred_soil"]
    cells = usable_cells(world, terrain, soil, preferred)

    sizes = seed_counts(len(cells))
    regions = partition(cells, [sizes[s] for s in PLACEMENT_ORDER])
    windows = tick_windows(sizes)

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
