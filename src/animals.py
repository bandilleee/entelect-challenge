"""Animals, world events, and plant-unlock tracking.

Three things the Level 1 simulator never needed and Level 2 cannot run without:

* **Animals** (``animals.json``) appear when their requirement tree evaluates
  true and *disappear again when it stops holding* - the problem statement is
  explicit about that ("Once the conditions for a particular animal are no
  longer met, that animal will also no longer be present in your world").
  A present animal applies ``effects`` that scale growth parameters of a target
  species or classification group.
* **Events** (``{"type":"event","tick":250,"event":"Rain"}`` in the level file).
  The unlock leaf ``{"type":"event","event":"Rain"}`` reads "has transpired at
  least once", so events latch from their tick onwards.
* **Unlock tracking** (``plant_unlock_conditions.json``).  Whether an unlock,
  once achieved, *stays* achieved is NOT stated anywhere.  Both readings are
  implemented and selected by :attr:`UnlockTracker.mode`; the difference is
  worth measuring because it decides whether the Level 2 scaffolding has to
  survive to tick 500.

DETERMINISM (platform rule 6)
-----------------------------
No RNG, no wall-clock.  Every traversal is over a list in file order or an
explicitly sorted list; nothing iterates a ``set``, so ``PYTHONHASHSEED``
cannot reach an output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------
# Group-name normalisation
# --------------------------------------------------------------------------
#: ``animals.json`` asks Rhizorends for ``"Shallow-root Species"``.
#: ``classifications.json`` spells the group ``"Shallowroot Species"``.
#: ``"Deep-root Species"`` *is* hyphenated in both files and matches fine, so
#: this looks like a typo on their side rather than a convention - but we do
#: not know whether their engine normalises.  Strict by default; the flag
#: exists so the cost of the bug can be measured rather than assumed.
def canonical_group_key(name: str) -> str:
    """Lower-cased, hyphen/underscore/space-stripped form of a group name."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def compare(value: float, operator: str, threshold: float) -> bool:
    try:
        fn = OPERATORS[str(operator)]
    except KeyError:  # pragma: no cover - guard against a new data file
        raise ValueError(f"unknown operator {operator!r}") from None
    return bool(fn(value, threshold))


# --------------------------------------------------------------------------
# Catalogue: names <-> indices, classification groups
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Catalogue:
    """Static name/index/group lookup shared by animals and unlocks."""

    name_of: Mapping[int, str]
    index_of: Mapping[str, int]
    groups: Mapping[str, tuple[str, ...]]          # exact spelling -> members
    groups_loose: Mapping[str, tuple[str, ...]]    # canonical key -> members

    @classmethod
    def from_files(cls, plant_dataset_path: str,
                   classifications_path: str) -> "Catalogue":
        with open(plant_dataset_path, "r", encoding="utf-8") as fh:
            plants = json.load(fh)
        with open(classifications_path, "r", encoding="utf-8") as fh:
            classes = json.load(fh)
        name_of = {int(p["index"]): str(p["plant"]) for p in plants}
        index_of = {str(p["plant"]): int(p["index"]) for p in plants}
        groups = {str(k): tuple(str(v) for v in vs) for k, vs in classes.items()}
        loose = {canonical_group_key(k): v for k, v in groups.items()}
        return cls(name_of, index_of, groups, loose)

    def resolve_group(self, entries: Sequence[str], normalise: bool
                      ) -> tuple[str, ...]:
        """``species_group`` -> concrete plant names.

        An entry may be a classification name *or* a bare plant name (the PDF's
        own ``group_coverage`` example lists plant names).  Unknown entries are
        passed through unchanged so they simply match nothing.
        """
        out: list[str] = []
        for entry in entries:
            key = str(entry)
            members = self.groups.get(key)
            if members is None and normalise:
                members = self.groups_loose.get(canonical_group_key(key))
            out.extend(members if members is not None else (key,))
        # de-duplicated, sorted: deterministic regardless of file order
        return tuple(sorted(set(out)))

    def indices_for(self, names: Iterable[str]) -> tuple[int, ...]:
        return tuple(sorted({self.index_of[n] for n in names
                             if n in self.index_of}))


# --------------------------------------------------------------------------
# The snapshot a condition tree is evaluated against
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class WorldSnapshot:
    """Everything a condition tree can ask about, at one tick."""

    counts: Mapping[int, int]           # plant index -> occupied cells
    total_cells: int                    # rows*cols  (the coverage denominator)
    populated: int                      # occupied cells, for `dominance`
    events: tuple[str, ...]             # events that have transpired, sorted
    animals: tuple[str, ...]            # animal names present, sorted
    features: Mapping[str, int] = field(default_factory=dict)

    def count_of(self, catalogue: Catalogue, name: str) -> int:
        idx = catalogue.index_of.get(name)
        return int(self.counts.get(idx, 0)) if idx is not None else 0

    def count_many(self, catalogue: Catalogue, names: Iterable[str]) -> int:
        return sum(self.count_of(catalogue, n) for n in names)


# --------------------------------------------------------------------------
# Animals
# --------------------------------------------------------------------------
EFFECT_TYPES = (
    "spread_rate",
    "maturation_rate",
    "spread_range",
    "seed_dispersal",
    "soil_nutrient_regeneration",
    "regression_rate",
)

#: Effect types that name a plant/group target rather than the soil.
PLANT_EFFECT_TYPES = ("spread_rate", "maturation_rate", "spread_range",
                      "seed_dispersal")


@dataclass(frozen=True)
class Animal:
    id: str
    name: str
    requirements: Mapping[str, Any]
    effects: tuple[Mapping[str, Any], ...]


class Animals:
    """``animals.json``, evaluated against a :class:`WorldSnapshot`."""

    def __init__(self, entries: Sequence[Mapping[str, Any]],
                 catalogue: Catalogue, normalise_group_names: bool = False):
        # file order is the evaluation order; it is a list, so it is stable
        self.entries = tuple(
            Animal(str(a["id"]), str(a.get("name", a["id"])),
                   a.get("requirements", {}) or {},
                   tuple(a.get("effects", ()) or ()))
            for a in entries)
        self.catalogue = catalogue
        self.normalise = bool(normalise_group_names)
        self.names = tuple(sorted({a.name for a in self.entries}))
        self.ids = tuple(sorted({a.id for a in self.entries}))

    @classmethod
    def from_file(cls, path: str, catalogue: Catalogue,
                  normalise_group_names: bool = False) -> "Animals":
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh), catalogue, normalise_group_names)

    # -- requirement trees -------------------------------------------------
    def _condition(self, node: Mapping[str, Any], snap: WorldSnapshot) -> bool:
        t = str(node.get("type", ""))
        cat = self.catalogue

        if t in ("AND", "OR"):
            kids = [self._condition(c, snap)
                    for c in node.get("conditions", ()) or ()]
            return all(kids) if t == "AND" else any(kids)
        if t == "NOT":
            kids = node.get("conditions") or ([node["condition"]]
                                              if "condition" in node else ())
            return not all(self._condition(c, snap) for c in kids)
        if t == "CONDITION":                       # documented wrapper node
            inner = node.get("conditions") or ()
            return all(self._condition(c, snap) for c in inner)

        if t == "coverage":
            names = node.get("species") or ()
            if isinstance(names, str):
                names = [names]
            n = snap.count_many(cat, names)
            frac = n / snap.total_cells if snap.total_cells else 0.0
            return compare(frac, node.get("operator", ">="),
                           float(node["threshold"]))
        if t == "group_coverage":
            names = cat.resolve_group(node.get("species_group", ()) or (),
                                      self.normalise)
            n = snap.count_many(cat, names)
            frac = n / snap.total_cells if snap.total_cells else 0.0
            return compare(frac, node.get("operator", ">="),
                           float(node["threshold"]))
        if t == "count":
            grp = node.get("species_group")
            if grp is not None:
                names = cat.resolve_group(grp, self.normalise)
            else:
                sp = node.get("species")
                names = list(sp) if isinstance(sp, (list, tuple)) else [sp]
            n = snap.count_many(cat, names)
            return compare(n, node.get("operator", ">="),
                           float(node["threshold"]))
        if t == "dominance":
            # "single_species": the largest species' share of populated cells.
            if not snap.populated:
                return False
            share = max(snap.counts.values(), default=0) / snap.populated
            return compare(share, node.get("operator", ">="),
                           float(node["threshold"]))
        if t == "species_present":
            s = str(node["species"])
            return s in snap.animals or snap.count_of(cat, s) > 0
        if t == "species_absent":
            s = str(node["species"])
            return not (s in snap.animals or snap.count_of(cat, s) > 0)
        if t == "event":
            return str(node["event"]) in snap.events
        if t == "feature_count":
            f = str(node["feature"])
            return compare(int(snap.features.get(f, 0)),
                           node.get("operator", ">="), float(node["value"]))
        raise ValueError(f"unknown animal condition type {t!r}")

    def present(self, snap: WorldSnapshot) -> tuple[str, ...]:
        """Animal *names* present under this snapshot, sorted.

        Evaluated to a fixed point, because ``species_present``/
        ``species_absent`` can reference other animals: at most ``len(entries)``
        passes are needed, and the loop is bounded so it always terminates.
        """
        present: list[str] = []
        for _ in range(len(self.entries) + 1):
            snap2 = WorldSnapshot(snap.counts, snap.total_cells, snap.populated,
                                  snap.events, tuple(sorted(present)),
                                  snap.features)
            found = [a.name for a in self.entries
                     if self._condition(a.requirements, snap2)]
            found.sort()
            if found == sorted(present):
                return tuple(found)
            present = found
        return tuple(sorted(present))

    # -- effects -----------------------------------------------------------
    def effects_for(self, present_names: Sequence[str]) -> "EffectSet":
        """Aggregate the effects of the named animals.

        Animals are applied in ``animals.json`` file order so that ``set``
        modes resolve identically every run.
        """
        eff = EffectSet()
        wanted = set(present_names)
        for animal in self.entries:
            if animal.name not in wanted:
                continue
            for e in animal.effects:
                etype = str(e.get("type", ""))
                if etype not in EFFECT_TYPES:
                    continue
                mode = str(e.get("mode", "multiply"))
                value = float(e.get("value", 1.0))
                target = str(e.get("target", ""))
                # Route by TARGET, not by type: `soil_nutrient_regeneration`
                # targets "soil" while `regression_rate` targets a plant group.
                if target == "soil":
                    eff.apply_global(etype, mode, value)
                else:
                    names = self.catalogue.resolve_group([target],
                                                         self.normalise)
                    for idx in self.catalogue.indices_for(names):
                        eff.apply(etype, idx, mode, value)
        return eff


class EffectSet:
    """Accumulated multipliers, keyed ``(effect_type, plant_index)``."""

    __slots__ = ("plant", "world")

    def __init__(self) -> None:
        self.plant: dict[tuple[str, int], float] = {}
        self.world: dict[str, float] = {}

    def apply(self, etype: str, idx: int, mode: str, value: float) -> None:
        key = (etype, int(idx))
        cur = self.plant.get(key, 1.0)
        if mode == "multiply":
            self.plant[key] = cur * value
        elif mode == "add":
            self.plant[key] = cur + value
        elif mode == "set":
            self.plant[key] = value
        else:  # pragma: no cover - guard against a new data file
            raise ValueError(f"unknown effect mode {mode!r}")

    def apply_global(self, etype: str, mode: str, value: float) -> None:
        cur = self.world.get(etype, 1.0)
        if mode == "multiply":
            self.world[etype] = cur * value
        elif mode == "add":
            self.world[etype] = cur + value
        elif mode == "set":
            self.world[etype] = value
        else:  # pragma: no cover
            raise ValueError(f"unknown effect mode {mode!r}")

    def factor(self, etype: str, idx: int) -> float:
        return self.plant.get((etype, int(idx)), 1.0)

    def world_factor(self, etype: str) -> float:
        return self.world.get(etype, 1.0)

    def key(self) -> tuple:
        """Hashable, order-independent identity - used to cache per-tick work."""
        return (tuple(sorted(self.plant.items())),
                tuple(sorted(self.world.items())))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EffectSet) and self.key() == other.key()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EffectSet(plant={self.plant}, world={self.world})"


# --------------------------------------------------------------------------
# Plant unlocks
# --------------------------------------------------------------------------
UNLOCK_MODES = ("latching", "live")

#: The five species every level starts with (problem statement, p.6).
STARTERS = ("Grass", "Rose Bush", "Lavender", "Dwarf Sunflower", "Oak Tree")


class UnlockTracker:
    """``plant_unlock_conditions.json`` evaluated each tick.

    ``mode="latching"`` - once a plant unlocks it stays unlocked.
    ``mode="live"``     - the tree is a live predicate, so a plant can re-lock
                          when coverage falls away.

    We do not know which the engine implements and it changes the entire Level 2
    strategy, so it is a flag rather than a decision.
    """

    def __init__(self, entries: Sequence[Mapping[str, Any]],
                 catalogue: Catalogue, animal_names: Sequence[str],
                 mode: str = "latching", normalise_group_names: bool = False):
        if mode not in UNLOCK_MODES:
            raise ValueError(f"unlock_mode must be one of {UNLOCK_MODES}")
        self.entries = tuple((str(e["plant"]), e["unlock"]) for e in entries)
        self.catalogue = catalogue
        self.animal_names = tuple(sorted(set(animal_names)))
        self.mode = mode
        self.normalise = bool(normalise_group_names)
        self.starters = tuple(n for n in STARTERS if n in catalogue.index_of)
        self._latched: list[str] = list(self.starters)

    def reset(self) -> None:
        self._latched = list(self.starters)

    def _node(self, node: Mapping[str, Any], snap: WorldSnapshot) -> bool:
        op = node.get("op")
        cat = self.catalogue
        if op == "AND":
            return all(self._node(c, snap) for c in node.get("children", ()))
        if op == "OR":
            return any(self._node(c, snap) for c in node.get("children", ()))
        if op == "NOT":
            return not self._node(node["child"], snap)

        t = str(node.get("type", ""))
        if t == "species_present":
            s = str(node["species"])
            if s in self.animal_names:
                return s in snap.animals
            return snap.count_of(cat, s) > 0
        if t == "species_absent":
            s = str(node["species"])
            if s in self.animal_names:
                return s not in snap.animals
            return snap.count_of(cat, s) == 0
        if t == "coverage":
            n = snap.count_of(cat, str(node["plant"]))
            frac = n / snap.total_cells if snap.total_cells else 0.0
            return compare(frac, node.get("operator", ">="),
                           float(node["value"]))
        if t == "count":
            n = snap.count_of(cat, str(node["plant"]))
            return compare(n, node.get("operator", ">="), float(node["value"]))
        if t == "event":
            return str(node["event"]) in snap.events
        if t == "feature_count":
            # `dead_matter` is given as a fraction (0.05) in the data file while
            # `burnt_soil` is a raw count (20); compare on whichever scale the
            # threshold implies.
            f = str(node["feature"])
            raw = int(snap.features.get(f, 0))
            value = float(node["value"])
            measure = (raw / snap.total_cells
                       if (0.0 < value < 1.0 and snap.total_cells) else raw)
            return compare(measure, node.get("operator", ">="), value)
        raise ValueError(f"unknown unlock condition type {t!r}")

    def evaluate(self, snap: WorldSnapshot) -> tuple[str, ...]:
        """Plant *names* placeable under this snapshot, sorted."""
        live = list(self.starters)
        for name, tree in self.entries:
            if self._node(tree, snap):
                live.append(name)
        if self.mode == "live":
            return tuple(sorted(set(live)))
        self._latched = sorted(set(self._latched) | set(live))
        return tuple(self._latched)

    def indices(self, names: Sequence[str]) -> tuple[int, ...]:
        return self.catalogue.indices_for(names)
