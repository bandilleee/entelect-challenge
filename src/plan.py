#!/usr/bin/env python3
"""Unlock planning: what to grow, how much of it, and in what order.

Level 1 had no unlock puzzle -- five starters and a fixed point. Level 2 turns
animals on and schedules a Rain event, which opens the graph to 28 species.
Since `H = log_31(S)` and the main term is `0.8 * H * coverage`, species count
is worth far more than any placement tuning, so walking that graph correctly is
the whole level.

This module turns the real condition trees in `plant_unlock_conditions.json`
and `animals.json` into a concrete, ordered growing plan. Nothing here is a
hand-copied table: the thresholds are read out of the data and converted to
absolute cell counts against the level's own `rows * cols`, so the same code
survives a Level 3 file with different numbers.

The condition walker is the one from `experiments/closure2.py`, extended rather
than rewritten: the same node types in the same order, but instead of returning
a boolean each branch returns the *requirement* that would make it true (or
None if nothing we can do makes it true). closure2 remains the second opinion --
`tests/test_plan.py` asserts that this module reaches the same species set.

Everything is deterministic: every iteration over a set is sorted first, OR
branches are broken by (cost, sorted key), and there is no RNG anywhere.
"""
import json
import math
import pathlib
from collections import namedtuple

# ---------------------------------------------------------------------------
# The one assumption we cannot test locally.
#
# LATCH = True  -> an unlock, once achieved, stays achieved even after the
#                  plants that triggered it die. Scaffolding is disposable and
#                  each tier can be grown, spent and abandoned in turn.
# LATCH = False -> the conditions are live predicates, re-evaluated every tick.
#                  Every prerequisite would have to be ALIVE at tick 500, and
#                  the scaffolding would compete with the scoring garden for
#                  space -- a materially harder problem.
#
# The conditions read as live predicates ("Checks whether a species exists"),
# but the submission log's `unlocked_plant_types` field settles it for free on
# the next submission. Until then we plan for LATCH and hedge inside phase B by
# placing prerequisites before their dependants (see solve.py).
LATCH = True

# Monocryx appears when any single species reaches 50% of the grid, and Amber
# Fern unlocks on `species_absent: Monocryx`. So no species may ever be allowed
# near half the board. This is also what the entropy term wants anyway.
DOMINANCE_FRACTION = 0.5

# Thresholds are strict `>`, and we do not know whether their coverage
# denominator is rows*cols or just the plantable cells. Using rows*cols gives
# the larger absolute target, which satisfies both readings, and then this
# margin is added on top.
SAFETY_FRACTION = 0.03
SAFETY_MINIMUM = 8

DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"

STARTERS = ("Grass", "Rose Bush", "Lavender", "Dwarf Sunflower", "Oak Tree")

# Emberroot Tree carries `burnt_soil_radius: 2`, so each mature tree is assumed
# to burn the Moore-radius-2 block around it (25 cells). `feature_count
# burnt_soil` is turned into a count of Emberroot Trees on that basis. It is a
# reading of the rule, not a measured fact -- flagged on the step it produces.
BURNT_CELLS_PER_EMBERROOT = 25

# A plant in a virgin cell holds 100 nutrients and drains 1/tick, so it dies
# about 100 ticks after it is planted and the cell is then flagged dead matter.
# `feature_count dead_matter` is satisfied by waiting, not by planting.
NUTRIENT_LIFETIME = 100

PlanStep = namedtuple("PlanStep", "plant required_cells depends_on")


# ---------------------------------------------------------------------------
# static data


def load_world(level):
    """Accept either a path to a level file or an already-parsed world dict."""
    if isinstance(level, dict):
        return level
    return json.loads(pathlib.Path(level).read_text())


def load_static(data_dir=None):
    d = pathlib.Path(data_dir) if data_dir else DATA
    return {
        "plants": json.loads((d / "plant_dataset.json").read_text()),
        "animals": json.loads((d / "animals.json").read_text()),
        "unlocks": json.loads((d / "plant_unlock_conditions.json").read_text()),
        "classes": json.loads((d / "classifications.json").read_text()),
    }


def expand_group(names, classes):
    """A species_group entry is either a classification name or a species name.

    Straight from closure2. `classifications.json` spells one group
    "Shallowroot Species" while the animal that wants it asks for
    "Shallow-root Species"; we do not normalise, because if their engine does
    not either then Rhizorends never appears and Bloodbloom stays blocked.
    Matching their literal spelling keeps our closure honest.
    """
    out = []
    for n in names:
        out.extend(classes.get(n, [n]))
    return out


def cells_for(operator, value, total, absolute=False):
    """Smallest integer cell count satisfying `count OP value`.

    `absolute` means the value is already a count (a `count` node) rather than
    a fraction of the board (a `coverage` node). Float noise is real here:
    0.05 * 7000 comes out as 350.00000000000006, so the comparison is snapped
    to the nearest integer before the strictness rule is applied.
    """
    target = float(value) if absolute else float(value) * total
    nearest = round(target)
    if abs(target - nearest) < 1e-9:
        target = float(nearest)
    if operator == ">":
        return int(math.floor(target)) + 1
    if operator == ">=":
        return int(math.ceil(target - 1e-9))
    raise ValueError(f"unsupported operator {operator!r}")


def with_margin(n, fraction=SAFETY_FRACTION, minimum=SAFETY_MINIMUM):
    """Aim over the threshold. Landing exactly on a strict `>` scores nothing."""
    return n + max(int(math.ceil(n * fraction)), minimum)


# ---------------------------------------------------------------------------
# requirement algebra
#
# A requirement is {key: int}, where key is ("plant", name) for live cells of a
# species, or ("event", name) for an event that must already have fired, or
# ("dead", "") for dead-matter cells. None means "no amount of growing makes
# this true right now".


def merge_max(reqs):
    out = {}
    for r in reqs:
        for k, v in r.items():
            if v > out.get(k, 0):
                out[k] = v
    return out


def cost(req):
    return sum(v for k, v in req.items() if k[0] != "event")


def _cheapest(options):
    """Deterministic OR resolution: cheapest, ties broken by sorted key."""
    best = None
    for opt in options:
        key = (cost(opt), tuple(sorted((k, v) for k, v in opt.items())))
        if best is None or key < best[0]:
            best = (key, opt)
    return None if best is None else best[1]


class State:
    """What is unlocked so far, plus the level's fixed facts."""

    def __init__(self, world, static):
        self.rows, self.cols = world["rows"], world["cols"]
        self.total = self.rows * self.cols
        self.animals_enabled = bool(world["animals_enabled"])
        self.events = {c["event"]: c["tick"]
                       for c in world.get("commands", [])
                       if c.get("type") == "event"}
        self.plants = {p["plant"]: p for p in static["plants"]}
        self.index = {p["plant"]: p["index"] for p in static["plants"]}
        self.animals = {a["name"]: a for a in static["animals"]}
        self.unlocks = static["unlocks"]
        self.classes = static["classes"]
        self.animal_names = set(self.animals) | {a["id"] for a in static["animals"]}
        self.plants_avail = set(STARTERS)
        self.animals_avail = set()
        self.dominance_cap = int(self.total * DOMINANCE_FRACTION) - 1
        # collected while evaluating one candidate, then committed by the caller
        self.touched_animals = set()

    def cap(self, n):
        return min(n, self.dominance_cap)


# --- animals ---------------------------------------------------------------


def animal_requirements(req, state, seen=()):
    """What must be growing for this animal to appear? Adapted from
    closure2.animal_present -- same branches, returning a requirement instead
    of a boolean."""
    t = req.get("type")
    if t in ("AND", "OR"):
        kids = [animal_requirements(c, state, seen)
                for c in req.get("conditions", [])]
        if t == "AND":
            return None if any(k is None for k in kids) else merge_max(kids)
        return _cheapest([k for k in kids if k is not None])
    if t == "NOT":
        inner = req.get("conditions") or [req.get("condition")]
        got = animal_requirements(inner[0], state, seen)
        # We control what we grow, so a NOT is satisfied by simply not growing
        # the thing -- unless it is unconditionally true, which none are.
        return {} if got is None or got else None
    if t == "coverage":
        species = sorted(req["species"])
        need = cells_for(req.get("operator", ">="), req["threshold"], state.total)
        avail = [s for s in species if s in state.plants_avail]
        if not avail:
            return None
        return {("plant", avail[0]): state.cap(need)}
    if t == "group_coverage":
        members = sorted(set(expand_group(req["species_group"], state.classes)))
        need = cells_for(req.get("operator", ">="), req["threshold"], state.total)
        avail = [s for s in members if s in state.plants_avail]
        if not avail:
            return None
        return {("plant", avail[0]): state.cap(need)}
    if t == "count":
        grp = req.get("species_group")
        if grp is not None:
            members = sorted(set(expand_group(grp, state.classes)))
        else:
            sp = req.get("species")
            members = sorted(sp) if isinstance(sp, list) else [sp]
        need = cells_for(req.get("operator", ">="), req["threshold"],
                         state.total, absolute=True)
        avail = [s for s in members if s in state.plants_avail]
        if not avail:
            return None
        return {("plant", avail[0]): state.cap(need)}
    if t == "dominance":
        # Monocryx. Never. Amber Fern unlocks on its ABSENCE, and a monoculture
        # would destroy the entropy term anyway.
        return None
    if t == "species_present":
        s = req["species"]
        if s in state.plants_avail:
            return {("plant", s): 1}
        if s in state.animal_names:
            return _animal_via(s, state, seen)
        return None
    if t == "species_absent":
        return {}
    raise ValueError(f"unknown animal condition: {t}")


def _animal_via(name, state, seen=()):
    if not state.animals_enabled:
        return None
    if LATCH and name in state.animals_avail:
        return {}
    if name in seen:
        return None
    animal = state.animals.get(name)
    if animal is None:
        return None
    got = animal_requirements(animal["requirements"], state, tuple(seen) + (name,))
    if got is not None:
        state.touched_animals.add(name)
    return got


# --- plants ----------------------------------------------------------------


def plant_requirements(node, state):
    """What must be growing for this plant to unlock? Adapted from
    closure2.plant_unlocked, same branches, requirement instead of boolean."""
    t = node.get("op") or node.get("type")
    if t == "AND":
        kids = [plant_requirements(c, state) for c in node["children"]]
        return None if any(k is None for k in kids) else merge_max(kids)
    if t == "OR":
        kids = [plant_requirements(c, state) for c in node["children"]]
        return _cheapest([k for k in kids if k is not None])
    if t == "NOT":
        got = plant_requirements(node["child"], state)
        return {} if got is None or got else None
    if t == "species_present":
        s = node["species"]
        if s in state.animal_names:
            return _animal_via(s, state)
        return {("plant", s): 1} if s in state.plants_avail else None
    if t == "species_absent":
        s = node["species"]
        if s in state.animal_names:
            # Monocryx is the only one that matters and we simply never trigger
            # it; any other animal we have already summoned is permanent.
            return {} if s not in state.animals_avail else None
        return {}                                  # a plant we decline to grow
    if t in ("coverage", "count"):
        p = node["plant"]
        if p not in state.plants_avail:
            return None
        need = cells_for(node.get("operator", ">"), node["value"], state.total,
                         absolute=(t == "count"))
        return {("plant", p): state.cap(need)}
    if t == "event":
        e = node["event"]
        return {("event", e): 1} if e in state.events else None
    if t == "feature_count":
        f = node["feature"]
        if f == "dead_matter":
            need = cells_for(node.get("operator", ">"), node["value"], state.total)
            return {("dead", ""): need}
        if f == "burnt_soil":
            if "Emberroot Tree" not in state.plants_avail:
                return None
            need = cells_for(node.get("operator", ">="), node["value"],
                             state.total, absolute=True)
            trees = max(1, -(-need // BURNT_CELLS_PER_EMBERROOT))
            return {("plant", "Emberroot Tree"): trees}
        return None
    raise ValueError(f"unknown plant condition: {t}")


# ---------------------------------------------------------------------------
# the plan


def unlock_stages(level_path, data_dir=None, margin=True):
    """Ordered scaffolding stages that walk the unlock graph.

    Each stage is a dict:
        grow        {plant name: cells to have alive at once}
        unlocks     [plant names this stage buys]
        animals     [animal names this stage summons]
        after_tick  earliest tick the stage may start (events), or 0
        dead_cells  dead-matter cells that must already exist, or 0
        notes       anything speculative about the stage

    One stage = one round of the closure fixpoint. Every plant unlockable in
    that round has its requirement merged into a single `grow`, so the stage
    is planted once and buys the whole round. That is more simultaneity than
    strictly needed, which is the safe direction.
    """
    world = load_world(level_path)
    static = load_static(data_dir)
    state = State(world, static)

    stages = []
    while True:
        candidates = {}
        animals_needed = set()
        for u in sorted(state.unlocks, key=lambda x: x["plant"]):
            name = u["plant"]
            if name in state.plants_avail:
                continue
            state.touched_animals = set()
            req = plant_requirements(u["unlock"], state)
            if req is not None:
                candidates[name] = req
                animals_needed |= state.touched_animals
        # Animals can also be summoned for their own sake (Barkskips gates
        # Worldtree Sapling), but they only ever appear as `species_present`
        # inside a plant condition, so the sweep above already finds them.
        if not candidates:
            break

        # Defer anything gated on an event that has not fired yet. Mire Bloom
        # needs Rain (tick 250); merging it into the round that unlocks it
        # would hold six other species hostage until tick 251 and push the
        # scaffolding past its 400-tick budget. It gets its own stage instead.
        plain = {k: v for k, v in candidates.items()
                 if not any(key[0] == "event" for key in v)}
        if plain and len(plain) < len(candidates):
            candidates = plain
            animals_needed = set()
            for name in sorted(candidates):
                state.touched_animals = set()
                node = next(u["unlock"] for u in state.unlocks
                            if u["plant"] == name)
                plant_requirements(node, state)
                animals_needed |= state.touched_animals

        merged = merge_max(candidates.values())
        grow = {k[1]: v for k, v in sorted(merged.items()) if k[0] == "plant"}
        events = sorted(k[1] for k in merged if k[0] == "event")
        dead = merged.get(("dead", ""), 0)
        notes = []
        if any(k[0] == "plant" and k[1] == "Emberroot Tree" for k in merged) \
                and "Ashroot Bramble" in candidates:
            notes.append("burnt_soil modelled as Emberroot Tree count "
                         f"(x{BURNT_CELLS_PER_EMBERROOT} cells each) -- unverified")
        if margin:
            grow = {p: state.cap(with_margin(n)) for p, n in grow.items()}

        stages.append({
            "grow": grow,
            "unlocks": sorted(candidates),
            "animals": sorted(animals_needed - state.animals_avail),
            "after_tick": max([state.events[e] for e in events], default=-1) + 1,
            "dead_cells": dead,
            "notes": notes,
        })
        state.plants_avail |= set(candidates)
        state.animals_avail |= animals_needed

    return stages, state


def unlock_plan(level_path, data_dir=None):
    """Flat ordered list of `(plant, required_cells, depends_on)`.

    `plant` is what to grow, `required_cells` how many of it must be alive at
    once, `depends_on` the plants that must already be unlocked before this
    step is reachable. Steps are in dependency order, so walking the list top
    to bottom walks the unlock graph from the five starters outward.
    """
    stages, state = unlock_stages(level_path, data_dir)
    unlocked_before = set(STARTERS)
    steps = []
    for stage in stages:
        deps = tuple(sorted(unlocked_before & set(stage["grow"])))
        for plant in sorted(stage["grow"], key=lambda p: state.index[p]):
            steps.append(PlanStep(plant, stage["grow"][plant], deps))
        unlocked_before |= set(stage["unlocks"])
    return steps


def reachable_species(level_path, data_dir=None):
    """Every plant the level can reach, in unlock order, as (index, name)."""
    stages, state = unlock_stages(level_path, data_dir)
    order = [(state.index[n], n) for n in sorted(STARTERS,
                                                 key=lambda p: state.index[p])]
    for stage in stages:
        for name in sorted(stage["unlocks"], key=lambda p: state.index[p]):
            order.append((state.index[name], name))
    return order, state


def placeable_species(level_path, soils_available, data_dir=None):
    """Reachable species that can actually sit on a cell of this map.

    Ashroot Bramble is the one that bites: `preferred_soil: [3]` and
    `must_be_burnt_soil`, and no level file ships burnt soil. It can be
    UNLOCKED (worth nothing on its own) but it cannot be planted unless an
    Emberroot Tree has burned ground first, so it is excluded here and the
    garden is built from what is left.
    """
    order, state = reachable_species(level_path, data_dir)
    soils = set(soils_available)
    out = []
    for idx, name in order:
        if soils & set(state.plants[name]["preferred_soil"]):
            out.append((idx, name))
    return out, state


def _report(level_path):
    stages, state = unlock_stages(level_path)
    order, _ = reachable_species(level_path)
    print(f"level {level_path}: {state.rows}x{state.cols} = {state.total} cells, "
          f"animals={state.animals_enabled}, events={sorted(state.events)}")
    print(f"LATCH = {LATCH}\n")
    running = 0
    for i, s in enumerate(stages, 1):
        total = sum(s["grow"].values())
        running += total
        ticks = -(-total // 20)
        print(f"stage {i}: {total:>5} cells / {ticks:>3} ticks"
              f"   after_tick>={s['after_tick']}  dead>={s['dead_cells']}")
        for p, n in sorted(s["grow"].items(), key=lambda kv: -kv[1]):
            print(f"      grow {p:<22} {n:>5}")
        print(f"      -> unlocks {', '.join(s['unlocks'])}")
        if s["animals"]:
            print(f"      -> animals {', '.join(s['animals'])}")
        for n in s["notes"]:
            print(f"      ! {n}")
    print(f"\nscaffolding total {running} cells "
          f"({-(-running // 20)} ticks at 20/tick)")
    print(f"reachable species: {len(order)}")
    placeable, _ = placeable_species(level_path, (0, 1, 2))
    print(f"placeable species: {len(placeable)} -> "
          f"{[n for _, n in placeable]}")


if __name__ == "__main__":
    import sys
    _report(sys.argv[1] if len(sys.argv) > 1 else str(DATA / "2 (1).json"))
