#!/usr/bin/env python3
"""Independent checker. Written before the solver, on purpose.

An invalid answer scores zero, so this is the file that protects the day.
It must NOT import from solve.py -- nor from src/sim.py or src/world.py.
The point is a second opinion, not the same code run twice, so the level
file is parsed here with plain json.load and the rules are re-stated from
harness/problem-spec.md rather than shared with the simulator.

Usage: python verify.py --input <level>.json --answer <schedule>.json
                        [--expect <n>] [--strict] [--quiet]
Exit 0 = valid, 1 = invalid. Prints COST=<n> for CI to pick up, where n is
the number of placements the organisers will actually apply (i.e. after
their silent truncation to the first 20 per tick).
"""
import argparse, json, pathlib, sys


def load(path):
    text = pathlib.Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ============================ REPLACE FROM HERE ============================

MAX_PLANTS_PER_TICK = 20            # organisers keep only the first 20
DEFAULT_TERRAIN = 0                 # cells absent from "cells" are dirt
DEFAULT_SOIL = 0
PLANTABLE_TERRAIN = 0               # 1 water, 2 stone -- uninhabitable

# Level 1 starters. Established in harness/problem-spec.md: the unlock
# closure from these five is a fixed point, so nothing else ever unlocks in
# a level with no animals and no events. Placing a locked plant is silently
# ignored by their engine -> our model would diverge -> treat as an error.
LEVEL1_UNLOCKED = (1, 2, 5, 6, 12)

_PLANT_DATASET = pathlib.Path(__file__).resolve().parent / "resources-docs" / "plant_dataset.json"


def load_plants(path=None):
    """{index: {"name":str, "soil":frozenset}} straight off plant_dataset.json."""
    p = pathlib.Path(path) if path else _PLANT_DATASET
    with open(p, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out = {}
    for entry in raw:
        out[int(entry["index"])] = {
            "name": entry.get("plant", "?"),
            "soil": frozenset(int(s) for s in entry.get("preferred_soil", [])),
        }
    return out


def build_terrain(level):
    """(terrain, soil) lookup for every in-bounds cell.

    Cells absent from the level's "cells" array default to terrain 0 /
    soil 0. Later duplicates in the array win, matching json-ish last-write
    semantics; duplicates are reported as a warning by check().
    """
    rows, cols = int(level["rows"]), int(level["cols"])
    terrain = [[DEFAULT_TERRAIN] * cols for _ in range(rows)]
    soil = [[DEFAULT_SOIL] * cols for _ in range(rows)]
    dupes = 0
    seen = set()
    for cell in level.get("cells", []):
        r, c = int(cell["row"]), int(cell["col"])
        if not (0 <= r < rows and 0 <= c < cols):
            continue                      # level file's problem, not ours
        if (r, c) in seen:
            dupes += 1
        seen.add((r, c))
        terrain[r][c] = int(cell.get("terrain", DEFAULT_TERRAIN))
        soil[r][c] = int(cell.get("soil", DEFAULT_SOIL))
    return terrain, soil, dupes


def unlocked_for(level):
    """Which plant indices this level ever offers.

    Level 1 shape -- no animals, season commands only -- means the five
    starters and nothing more. Any other shape: we cannot prove the set
    here, so return None and the legality check is skipped with a note.
    """
    if level.get("animals_enabled"):
        return None
    cmds = level.get("commands", [])
    if all(str(c.get("type", "")).lower() == "season" for c in cmds):
        return frozenset(LEVEL1_UNLOCKED)
    return None


def check(level, answer, plants=None, strict=False):
    """Return (ok, cost, problems, report).

    problems -> hard errors; a non-empty list means INVALID and exit 1.
    report["warnings"] -> things that do not invalidate but mean the
    organisers' run will differ from what we modelled. Under --strict the
    warnings are promoted to errors.

    Deliberately paranoid. Every check here maps to a way of scoring zero.
    """
    problems, warnings, notes = [], [], []
    report = {"warnings": warnings, "notes": notes, "stats": {}}

    if not isinstance(level, dict) or "rows" not in level or "cols" not in level:
        return False, None, ["--input is not a level file (no rows/cols)"], report
    rows, cols = int(level["rows"]), int(level["cols"])
    T = int(level["ticks"])

    if not isinstance(answer, dict):
        return False, None, ["answer must be a JSON object"], report
    if "actions" not in answer:
        return False, None, ["answer must have an 'actions' key"], report
    actions = answer["actions"]
    if not isinstance(actions, list):
        return False, None, ["'actions' must be a list"], report

    extra_top = sorted(set(answer) - {"actions"})
    if extra_top:
        warnings.append(f"unexpected top-level keys ignored by the engine: {extra_top}")

    if plants is None:
        plants = load_plants()
    unlocked = unlocked_for(level)
    if unlocked is None:
        notes.append("unlock set not provable for this level; "
                     "plant-legality check skipped")

    terrain, soil, cell_dupes = build_terrain(level)
    if cell_dupes:
        notes.append(f"level file lists {cell_dupes} duplicate cell(s); last wins")

    per_tick = {}            # tick -> count declared
    applied = 0              # count after the 20/tick truncation
    species_counts = {}
    seen_placement = set()   # (tick,row,col)
    dup_placements = []
    over_cap_ticks = []
    at_cap_ticks = []
    ticks_seen = []
    dup_tick_entries = []

    for ai, action in enumerate(actions):
        where = f"actions[{ai}]"
        if not isinstance(action, dict):
            problems.append(f"{where} must be an object")
            continue
        if "tick" not in action or "plants" not in action:
            problems.append(f"{where} must have 'tick' and 'plants'")
            continue
        extra = sorted(set(action) - {"tick", "plants"})
        if extra:
            warnings.append(f"{where} has unexpected keys {extra}")

        tick = action["tick"]
        if isinstance(tick, bool) or not isinstance(tick, int):
            problems.append(f"{where}.tick must be an integer, got {tick!r}")
            continue
        if not (0 <= tick <= T - 1):
            problems.append(
                f"{where}.tick={tick} outside [0,{T - 1}] "
                f"(ticks:{T} means {T} updates, last index {T - 1})")
            continue
        ticks_seen.append(tick)
        if tick in per_tick:
            dup_tick_entries.append(tick)

        plist = action["plants"]
        if not isinstance(plist, list):
            problems.append(f"{where}.plants must be a list")
            continue

        n = len(plist)
        per_tick[tick] = per_tick.get(tick, 0) + n
        if n == MAX_PLANTS_PER_TICK:
            at_cap_ticks.append(tick)

        for pi, pl in enumerate(plist):
            slot = f"{where}.plants[{pi}] (tick {tick})"
            if not isinstance(pl, dict):
                problems.append(f"{slot} must be an object")
                continue
            if "plant_index" not in pl:
                problems.append(
                    f"{slot} missing 'plant_index' "
                    f"(the PDF's schema block says 'index'; the worked "
                    f"example says 'plant_index' -- we emit 'plant_index')")
                continue
            missing = [f for f in ("row", "col") if f not in pl]
            if missing:
                problems.append(f"{slot} missing {missing}")
                continue

            idx, r, c = pl["plant_index"], pl["row"], pl["col"]
            bad_type = False
            for nm, val in (("plant_index", idx), ("row", r), ("col", c)):
                if isinstance(val, bool) or not isinstance(val, int):
                    problems.append(f"{slot}.{nm} must be an integer, got {val!r}")
                    bad_type = True
            if bad_type:
                continue

            in_bounds = 0 <= r < rows and 0 <= c < cols
            if not in_bounds:
                problems.append(
                    f"{slot} out of bounds: (row={r},col={c}) not in "
                    f"[0,{rows}) x [0,{cols})")

            if idx not in plants:
                problems.append(
                    f"{slot} plant_index={idx} is not in plant_dataset.json")
                continue
            pname = plants[idx]["name"]
            if unlocked is not None and idx not in unlocked:
                problems.append(
                    f"{slot} plant_index={idx} ({pname}) is LOCKED in this "
                    f"level -- the engine silently ignores it. Unlocked: "
                    f"{sorted(unlocked)}")

            if in_bounds:
                t, s = terrain[r][c], soil[r][c]
                if t != PLANTABLE_TERRAIN:
                    kind = {1: "water", 2: "stone"}.get(t, f"terrain {t}")
                    problems.append(
                        f"{slot} target ({r},{c}) is {kind}, not plantable")
                elif s not in plants[idx]["soil"]:
                    sname = {0: "dirt", 1: "mud", 2: "clay", 3: "burnt"}.get(s, f"soil {s}")
                    problems.append(
                        f"{slot} soil mismatch: ({r},{c}) is {sname} (soil {s}); "
                        f"{pname} prefers {sorted(plants[idx]['soil'])}")

                key = (tick, r, c)
                if key in seen_placement:
                    dup_placements.append(key)
                seen_placement.add(key)

            species_counts[idx] = species_counts.get(idx, 0) + 1

    for tick in sorted(per_tick):
        if per_tick[tick] > MAX_PLANTS_PER_TICK:
            over_cap_ticks.append((tick, per_tick[tick]))
        applied += min(per_tick[tick], MAX_PLANTS_PER_TICK)

    if over_cap_ticks:
        worst = max(n for _, n in over_cap_ticks)
        dropped = sum(n - MAX_PLANTS_PER_TICK for _, n in over_cap_ticks)
        warnings.append(
            f"*** {len(over_cap_ticks)} tick(s) exceed the {MAX_PLANTS_PER_TICK} "
            f"placements/tick cap (worst: {worst}). The organisers SILENTLY "
            f"keep only the first {MAX_PLANTS_PER_TICK} -- {dropped} placement(s) "
            f"will be dropped and their run will NOT match our model. "
            f"Ticks: {[t for t, _ in over_cap_ticks][:20]}")
    if dup_tick_entries:
        warnings.append(
            f"tick(s) appear in more than one action entry: "
            f"{sorted(set(dup_tick_entries))[:20]} -- the per-tick cap applies "
            f"to the total, and the engine may only honour the first entry")
    if dup_placements:
        uniq = sorted(set(dup_placements))
        warnings.append(
            f"{len(dup_placements)} duplicate (tick,row,col) placement(s); "
            f"the later one overwrites the earlier, wasting a slot. "
            f"First few: {uniq[:10]}")

    total = sum(per_tick.values())
    report["stats"] = {
        "total_placements": total,
        "applied_after_cap": applied,
        "distinct_ticks": len(per_tick),
        "tick_min": min(ticks_seen) if ticks_seen else None,
        "tick_max": max(ticks_seen) if ticks_seen else None,
        "tick_limit": T - 1,
        "grid": f"{rows}x{cols}",
        "per_species": {str(i): species_counts[i] for i in sorted(species_counts)},
        "per_species_named": {
            plants[i]["name"] if i in plants else f"#{i}": species_counts[i]
            for i in sorted(species_counts)},
        "ticks_at_cap": sorted(at_cap_ticks),
        "ticks_over_cap": over_cap_ticks,
        "duplicate_placements": len(dup_placements),
    }

    if strict:
        problems = problems + [f"(strict) {w}" for w in warnings]
    return (not problems), applied, problems, report
# ============================= TO HERE =====================================


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--answer", required=True)
    p.add_argument("--expect", type=float, default=None)
    p.add_argument("--strict", action="store_true",
                   help="promote warnings (over-cap, duplicates) to errors")
    p.add_argument("--quiet", action="store_true", help="suppress the summary")
    a = p.parse_args()

    ok, cost, problems, report = check(load(a.input), load(a.answer),
                                       strict=a.strict)
    for m in report.get("notes", []):
        print(f"  . {m}")
    if not a.strict:
        for w in report.get("warnings", []):
            print(f"  W {w}")
    for m in problems[:100]:
        print(f"  ! {m}")
    if len(problems) > 100:
        print(f"  ! ... and {len(problems) - 100} more")

    if not a.quiet and report.get("stats"):
        s = report["stats"]
        print(f"  - grid {s['grid']}, ticks 0..{s['tick_limit']}")
        print(f"  - placements: {s['total_placements']} declared, "
              f"{s['applied_after_cap']} applied after the cap, "
              f"over {s['distinct_ticks']} distinct tick(s)")
        print(f"  - tick range used: {s['tick_min']}..{s['tick_max']}")
        print(f"  - per species: {s['per_species_named']}")
        print(f"  - ticks at the {MAX_PLANTS_PER_TICK} cap: "
              f"{len(s['ticks_at_cap'])}"
              + (f" {s['ticks_at_cap'][:20]}" if s['ticks_at_cap'] else ""))
        if s["ticks_over_cap"]:
            print(f"  - ticks OVER the cap: {s['ticks_over_cap'][:20]}")
        if s["duplicate_placements"]:
            print(f"  - duplicate (tick,row,col): {s['duplicate_placements']}")

    print(f"COST={cost}")
    if not ok:
        print("INVALID")
        print("INVALID", file=sys.stderr)
        sys.exit(1)
    if a.expect is not None and cost != a.expect:
        print(f"MISMATCH: expected {a.expect}, got {cost}", file=sys.stderr)
        sys.exit(1)
    print("VALID")


if __name__ == "__main__":
    main()
