#!/usr/bin/env python3
"""Unlock closure with animals and events -- how many species can a level reach?

Level 1 had `animals_enabled: false` and no events, so nothing unlocked and the
answer was five. Level 2 turns animals on and schedules a Rain event, which
opens the unlock graph for the first time. Since `H = log_31(S)`, and the main
score term is `0.8 * H * coverage`, each extra species is worth far more than
any placement tuning -- so this number decides the whole level.

The evaluation is deliberately OPTIMISTIC: any unlocked plant is assumed able to
reach any coverage or count threshold. That makes the result an upper bound, so
a small answer is trustworthy while a large one still needs a schedule that
actually hits the thresholds.

Animals are part of the fixed point: a plant unlocks an animal by coverage, and
the animal's presence unlocks further plants, so plants and animals are grown
together until nothing more appears.

Usage: python experiments/closure2.py '<level>.json'
"""
import json
import pathlib
import sys

DATA = pathlib.Path(__file__).resolve().parent.parent / "resources-docs"
STARTERS = {"Grass", "Rose Bush", "Lavender", "Dwarf Sunflower", "Oak Tree"}
CLASSES = json.loads((DATA / "classifications.json").read_text())


def expand_group(names):
    """A species_group entry may be a classification name or a species name."""
    out = []
    for n in names:
        out.extend(CLASSES.get(n, [n]))
    return out


def load(level_path):
    return (json.loads(pathlib.Path(level_path).read_text()),
            json.loads((DATA / "plant_dataset.json").read_text()),
            json.loads((DATA / "animals.json").read_text()),
            json.loads((DATA / "plant_unlock_conditions.json").read_text()),
            json.loads((DATA / "classifications.json").read_text()))


def animal_present(req, plants_avail, animals_avail):
    """Can this animal's requirement tree be satisfied, optimistically?"""
    t = req.get("type")
    if t in ("AND", "OR"):
        kids = [animal_present(c, plants_avail, animals_avail)
                for c in req.get("conditions", [])]
        return all(kids) if t == "AND" else any(kids)
    if t == "NOT":
        inner = req.get("conditions") or [req.get("condition")]
        return not animal_present(inner[0], plants_avail, animals_avail)
    if t == "coverage":
        return all(s in plants_avail for s in req["species"])
    if t == "group_coverage":
        return any(s in plants_avail for s in expand_group(req["species_group"]))
    if t == "count":
        grp = req.get("species_group")
        if grp is not None:
            # a group name resolves through classifications; a bare list is
            # already the species
            return any(s in plants_avail for s in expand_group(grp))
        sp = req.get("species")
        if isinstance(sp, list):
            return any(s in plants_avail for s in sp)
        return sp in plants_avail
    if t == "dominance":
        # Monocryx appears only if one species holds >= 50% of the grid. That is
        # entirely under our control, and we never want it: Amber Fern unlocks
        # on `species_absent: Monocryx`, and a monoculture would wreck entropy
        # anyway. So this is always False for us.
        return False
    if t == "species_present":
        return req["species"] in animals_avail or req["species"] in plants_avail
    if t == "species_absent":
        return True                      # we can choose not to grow it
    raise ValueError(f"unknown animal condition: {t}")


def plant_unlocked(node, plants_avail, animals_avail, events, animal_names):
    t = node.get("op") or node.get("type")
    if t == "AND":
        return all(plant_unlocked(c, plants_avail, animals_avail, events,
                                  animal_names) for c in node["children"])
    if t == "OR":
        return any(plant_unlocked(c, plants_avail, animals_avail, events,
                                  animal_names) for c in node["children"])
    if t == "NOT":
        return not plant_unlocked(node["child"], plants_avail, animals_avail,
                                  events, animal_names)
    if t == "species_present":
        s = node["species"]
        return s in animals_avail if s in animal_names else s in plants_avail
    if t == "species_absent":
        s = node["species"]
        # An animal we cannot avoid once its trigger plants exist; a plant we
        # can simply decline to grow.
        return s not in animals_avail if s in animal_names else True
    if t in ("coverage", "count"):
        return node["plant"] in plants_avail
    if t == "event":
        return node["event"] in events
    if t == "feature_count":
        f = node["feature"]
        if f == "dead_matter":
            return True                          # plants die, matter appears
        if f == "burnt_soil":
            return "Emberroot Tree" in plants_avail
        return False
    raise ValueError(f"unknown plant condition: {t}")


def main():
    level_path = sys.argv[1] if len(sys.argv) > 1 else str(DATA / "1(1).json")
    world, plants, animals, unlocks, _ = load(level_path)

    animal_names = {a["name"] for a in animals} | {a["id"] for a in animals}
    events = {c["event"] for c in world["commands"] if c.get("type") == "event"}
    enabled = world["animals_enabled"]

    print(f"level: {level_path}")
    print(f"  grid {world['rows']}x{world['cols']}  ticks {world['ticks']}")
    print(f"  animals_enabled = {enabled}")
    print(f"  events scheduled = {sorted(events) or 'none'}\n")

    plants_avail = set(STARTERS)
    animals_avail = set()
    log = []
    changed = True
    while changed:
        changed = False
        if enabled:
            for a in animals:
                if a["name"] in animals_avail:
                    continue
                if animal_present(a["requirements"], plants_avail, animals_avail):
                    animals_avail.add(a["name"])
                    log.append(("animal", a["name"]))
                    changed = True
        for u in unlocks:
            p = u["plant"]
            if p in plants_avail:
                continue
            if plant_unlocked(u["unlock"], plants_avail, animals_avail,
                              events, animal_names):
                plants_avail.add(p)
                log.append(("plant", p))
                changed = True

    print("unlock order (optimistic):")
    for kind, name in log:
        print(f"   {kind:<7} {name}")

    all_plants = {p["plant"] for p in plants}
    blocked = sorted(all_plants - plants_avail)
    print(f"\nSPECIES REACHABLE: {len(plants_avail)} of {len(all_plants)}")
    print(f"animals present:   {len(animals_avail)} of {len(animals)}"
          f"  {sorted(animals_avail)}")
    if blocked:
        print(f"\nblocked ({len(blocked)}):")
        for b in blocked:
            node = next((u["unlock"] for u in unlocks if u["plant"] == b), None)
            print(f"   {b:<22} {json.dumps(node)[:90] if node else 'no rule'}")

    import math
    n = len(all_plants)
    usable = sum(
        1 for c in [(r, col) for r in range(world["rows"])
                    for col in range(world["cols"])]
    )
    print(f"\nH ceiling at {len(plants_avail)} species = "
          f"log_{n}({len(plants_avail)}) = "
          f"{math.log(len(plants_avail), n):.4f}")


if __name__ == "__main__":
    main()
