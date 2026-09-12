"""Our reconstruction of the organisers' Photospheria simulator.

    simulate(world, plants, schedule, rules=Rules(), record=None) -> FinalState

Every modelled rule sits behind its own boolean on :class:`Rules` so it can be
switched off in isolation during calibration, and the *within-tick phase order*
- which the problem statement never states - is itself a configurable tuple.

DETERMINISM (platform rule 6)
-----------------------------
* No RNG anywhere.  No wall-clock anywhere.
* No iteration over a ``set``; every ordered traversal is over a sorted list or
  a list in file order, so ``PYTHONHASHSEED`` cannot reach the output.
* Competition ties are broken by *unique integer keys*, never by dict order.

Ordering conventions that stand in for the unspecified "spread order"
--------------------------------------------------------------------
Spread is resolved per species, all sources of a species acting simultaneously
(sources of the same species cannot disagree about the outcome).  Species are
processed in ascending ``plant_index``, so "the last plant to spread in" is
canonicalised as "the highest plant index among the contenders".  This is an
assumption; it is deterministic and documented rather than incidental.
"""

from __future__ import annotations

import pathlib as _pathlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .animals import Animals, Catalogue, UnlockTracker, WorldSnapshot
from .world import Plant, World

DEFAULT_PHASE_ORDER = (
    "season",
    "placements",
    "spread",
    "age",
    "nutrient",
    "death",
)

COMPETITION_MODES = ("rank", "last_wins", "hybrid")

OVERWRITE_MODES = ("never", "rank", "immature_only", "rank_or_immature",
                   "always")

#: Where the static data files live when the caller does not say.
_DATA = _pathlib.Path(__file__).resolve().parent.parent / "resources-docs"


# ==========================================================================
# Rules
# ==========================================================================
@dataclass(frozen=True)
class Rules:
    """Every modelled mechanic, individually switchable.

    The numbered groups match the brief's rule list.
    """

    # -- 1. nutrient drain -> death -> dead-matter flag --------------------
    nutrient_drain: bool = True
    nutrient_start: float = 100.0
    drain_virgin: float = 1.0
    drain_dead_matter: float = 0.5
    regen_rate: float = 1.0
    regen_cap: float = 100.0
    #: "A plant can only begin competing for nutrient capacity in a cell once
    #: it has matured" (problem statement p.5) contradicts "While a plant
    #: occupies a cell, its nutrient points decrease at a rate of 1 point per
    #: tick" (p.6).  Under the first reading the drain clock starts at maturity,
    #: which moves every plant across the life/death boundary by
    #: ``time_to_maturity`` ticks.  Off = the p.6 reading.
    drain_from_maturity: bool = False
    #: dead matter is flagged only when the plant starved; a plant killed by
    #: shade leaves a cell that is still fertile.  [assumption]
    dead_matter_on_nonnutrient_death: bool = False
    #: once flagged, a cell stays flagged (all later generations drain at the
    #: reduced rate).  [assumption]
    dead_matter_persists: bool = True
    #: a cell at <= 0 nutrients is uninhabitable, so nothing may enter it.
    require_nutrient_to_enter: bool = True

    # -- 2. maturity clock ------------------------------------------------
    maturity: bool = True

    # -- 3. spread timing + geometry --------------------------------------
    spread: bool = True
    #: "since_maturity"  - first spread on the tick the plant matures, then
    #:                      every ``spread_rate`` ticks.
    #: "delayed_maturity" - first spread ``spread_rate`` ticks AFTER maturity.
    #: "since_planting"   - ``age % spread_rate == 0`` once mature.
    #: These differ a lot: under "since_maturity" a seedling spreads again the
    #: tick after it is born, so a wavefront advances one cell per tick and
    #: ``spread_rate`` only throttles re-spread, not the front.  OPEN QUESTION.
    spread_clock: str = "since_maturity"
    #: CrossHatch read as the diagonal X.  If False it is read as
    #: VonNeumann + diagonals (i.e. Moore-shaped).  [assumption]
    crosshatch_diagonal_only: bool = True
    #: a spreader never overwrites a plant of its own species.
    same_species_no_replace: bool = True
    #: "Spread range determines the radius around the plant that is INCLUDED in
    #: its spread_type pattern" reads as a filled disc.  The alternative is that
    #: a spread action lands only at exactly ``spread_range`` (a jump, leaving
    #: the inner ring untouched).  Off = filled disc.
    spread_ring_only: bool = False

    # -- 5b. what spread may do to an ALREADY OCCUPIED cell ----------------
    #: The single highest-leverage unknown, and the one the Level 1 engine logs
    #: disagree with our model about.
    #:   "never"            - spread writes into empty cells only.  Competition
    #:                        then only ever arbitrates two spreaders landing on
    #:                        the same empty cell in the same tick.
    #:   "rank"             - a spreader takes an occupied cell when its
    #:                        invasiveness_rank is strictly higher (p.6).
    #:   "immature_only"    - a spreader takes an occupied cell only while the
    #:                        occupant is still a seedling (p.13's literal
    #:                        reading: "neither plant has reached maturity at
    #:                        that point").
    #:   "rank_or_immature" - either of the two above.
    #:   "always"           - any spreader displaces any occupant.
    #: ``None`` derives the mode from ``competition`` exactly as the pre-
    #: calibration simulator did, so existing results are reproducible.
    spread_overwrite: str | None = None

    # -- 4. soil filtering -------------------------------------------------
    soil_filter: bool = True

    # -- 5. competition resolution ----------------------------------------
    #: "rank" | "last_wins" | "hybrid"  (see module docstring / brief section 3)
    competition: str = "hybrid"

    # -- 6. shade ----------------------------------------------------------
    shade: bool = True
    #: ``no_shade_survival`` kills the plant outright.  Separable from
    #: ``no_shade_spread``, which only blocks propagation.
    shade_kill: bool = True
    #: only a mature shade-caster casts shade.  [assumption]
    shade_requires_maturity: bool = True
    #: "chebyshev" (square) or "manhattan" (diamond) or "euclidean".
    shade_metric: str = "chebyshev"
    #: ``adjacent_shade_penalty`` semantics are undocumented.  When enabled it
    #: doubles the effective spread rate of a plant that is Moore-adjacent to a
    #: shaded cell.  Off by default - we have no evidence for it.
    adjacent_shade_penalty: bool = False

    # -- 7. seasons --------------------------------------------------------
    season_spread: bool = True  # honour no_winter_spread
    winter_name: str = "Winter"

    # -- 8. dead-matter re-entry ------------------------------------------
    dead_matter_reentry: bool = True  # 0.5/tick drain on flagged cells

    # -- 9. Level 2: events, animals, unlocks ------------------------------
    #: honour ``{"type":"event","tick":N,"event":"Rain"}`` in the level file.
    events: bool = True
    #: evaluate ``animals.json`` every tick and apply the effects of whichever
    #: animals are present.  Gated by the level's own ``animals_enabled``.
    animals: bool = True
    #: force animals on/off regardless of the level flag (calibration only).
    animals_override: bool | None = None
    #: ``animals.json`` asks for ``"Shallow-root Species"``;
    #: ``classifications.json`` spells it ``"Shallowroot Species"``.  Strict by
    #: default - turn on to accept both spellings.
    normalise_group_names: bool = False
    #: evaluate ``plant_unlock_conditions.json`` each tick and reject
    #: placements of plants that are not (yet) placeable.
    unlocks: bool = True
    #: "latching" - once unlocked, stays unlocked.
    #: "live"     - re-evaluated every tick, so a plant can re-lock.
    #: Unknown, and it decides the whole Level 2 strategy.  Measure both.
    unlock_mode: str = "latching"
    #: denominator for every ``coverage`` / ``group_coverage`` threshold.
    #: "all_cells" = rows*cols (the PDF's "if the world had 100 cells"),
    #: "plantable" = only cells a plant could ever occupy.
    coverage_denominator: str = "all_cells"
    #: animal ``spread_rate``/``maturation_rate`` effects are multipliers on a
    #: *rate*, but the underlying fields are *intervals in ticks*.  "divide"
    #: reads a 1.5x multiplier as "spreads 1.5x as often" (interval / 1.5);
    #: "multiply" reads it as a literal override of the field (interval * 1.5).
    effect_rate_semantics: str = "divide"

    # -- mechanics / harness ----------------------------------------------
    max_placements_per_tick: int = 20
    #: None = every plant index is unlocked.  A tuple restricts placements.
    #: Applied *in addition to* ``unlocks``.
    allowed_plants: tuple[int, ...] | None = None
    #: ``ticks: 500`` read as 500 updates over ticks 0..499.  The problem
    #: statement says "final actions occur on the penultimate day, and scoring
    #: is done on the state of the world on the final day", i.e. ticks 0..T
    #: inclusive - which is what ``True`` models.
    inclusive_end: bool = False
    phase_order: tuple[str, ...] = DEFAULT_PHASE_ORDER

    def __post_init__(self) -> None:
        if self.competition not in COMPETITION_MODES:
            raise ValueError(f"competition must be one of {COMPETITION_MODES}")
        if self.spread_clock not in ("since_maturity", "delayed_maturity",
                                     "since_planting"):
            raise ValueError(
                "spread_clock must be since_maturity|delayed_maturity|since_planting")
        if self.spread_overwrite is not None \
                and self.spread_overwrite not in OVERWRITE_MODES:
            raise ValueError(f"spread_overwrite must be one of {OVERWRITE_MODES}")
        if self.unlock_mode not in ("latching", "live"):
            raise ValueError("unlock_mode must be latching|live")
        if self.coverage_denominator not in ("all_cells", "plantable"):
            raise ValueError("coverage_denominator must be all_cells|plantable")
        if self.effect_rate_semantics not in ("divide", "multiply"):
            raise ValueError("effect_rate_semantics must be divide|multiply")
        unknown = [p for p in self.phase_order if p not in DEFAULT_PHASE_ORDER]
        if unknown:
            raise ValueError(f"unknown phases: {unknown}")

    # -- derived -----------------------------------------------------------
    @property
    def overwrite_mode(self) -> str:
        """``spread_overwrite``, defaulted from ``competition`` for back-compat."""
        if self.spread_overwrite is not None:
            return self.spread_overwrite
        return "always" if self.competition == "last_wins" else "rank"


# ==========================================================================
# State
# ==========================================================================
class State:
    """Grid state at one instant.  ``FinalState`` is an alias of this."""

    __slots__ = ("rows", "cols", "ticks", "tick", "grid", "lifespan",
                 "nutrient", "dead_matter", "season", "world",
                 "unlocked_plant_types", "animals_present", "events_seen")

    def __init__(self, rows, cols, ticks, tick, grid, lifespan, nutrient,
                 dead_matter, season, world=None, unlocked_plant_types=(),
                 animals_present=(), events_seen=()):
        self.rows = int(rows)
        self.cols = int(cols)
        self.ticks = int(ticks)
        self.tick = int(tick)
        self.grid = grid  # int16 (rows, cols) plant index, 0 = empty
        self.lifespan = lifespan  # int32 (rows, cols)
        self.nutrient = nutrient  # float32
        self.dead_matter = dead_matter  # bool
        self.season = season
        self.world = world
        #: plant NAMES the engine would report as placeable, sorted.  The
        #: engine's own evaluation log carries a field of the same name, so
        #: this is directly comparable against ground truth.
        self.unlocked_plant_types = tuple(unlocked_plant_types)
        self.animals_present = tuple(animals_present)
        self.events_seen = tuple(events_seen)

    def to_dict(self) -> dict[str, Any]:
        """Exactly the shape the scorer consumes - nothing more."""
        return {
            "rows": self.rows,
            "cols": self.cols,
            "ticks": self.ticks,
            "grid": [[int(v) for v in row] for row in self.grid],
            "lifespan": [[int(v) for v in row] for row in self.lifespan],
        }

    def copy(self) -> "State":
        return State(self.rows, self.cols, self.ticks, self.tick,
                     self.grid.copy(), self.lifespan.copy(),
                     self.nutrient.copy(), self.dead_matter.copy(),
                     self.season, self.world, self.unlocked_plant_types,
                     self.animals_present, self.events_seen)


FinalState = State


# ==========================================================================
# Geometry helpers
# ==========================================================================
def spread_offsets(spread_type: str, rng: int, crosshatch_diagonal_only: bool = True,
                   ring_only: bool = False) -> tuple[tuple[int, int], ...]:
    """Deterministic, sorted offset list for a spread geometry.

    ``ring_only`` keeps only the cells at *exactly* ``rng`` in the pattern's own
    metric - the reading in which a spread action is a jump rather than a
    filled disc.
    """
    offs: list[tuple[int, int]] = []
    r = int(rng)
    if ring_only:
        full = spread_offsets(spread_type, r, crosshatch_diagonal_only)
        if spread_type == "VonNeumann":
            keep = [o for o in full if abs(o[0]) + abs(o[1]) == r]
        else:
            keep = [o for o in full if max(abs(o[0]), abs(o[1])) == r]
        return tuple(sorted(keep))
    if spread_type == "VonNeumann":
        for dr in range(-r, r + 1):
            for dc in range(-r, r + 1):
                if (dr or dc) and abs(dr) + abs(dc) <= r:
                    offs.append((dr, dc))
    elif spread_type == "Moore":
        for dr in range(-r, r + 1):
            for dc in range(-r, r + 1):
                if dr or dc:
                    offs.append((dr, dc))
    elif spread_type == "Row":
        for dc in range(-r, r + 1):
            if dc:
                offs.append((0, dc))
    elif spread_type == "Column":
        for dr in range(-r, r + 1):
            if dr:
                offs.append((dr, 0))
    elif spread_type == "CrossHatch":
        if crosshatch_diagonal_only:
            for d in range(1, r + 1):
                offs += [(-d, -d), (-d, d), (d, -d), (d, d)]
        else:
            for dr in range(-r, r + 1):
                for dc in range(-r, r + 1):
                    if (dr or dc) and (abs(dr) + abs(dc) <= r or abs(dr) == abs(dc)):
                        offs.append((dr, dc))
    else:
        raise ValueError(f"unknown spread_type {spread_type!r}")
    return tuple(sorted(set(offs)))


def _shift_or(out: np.ndarray, src: np.ndarray, dr: int, dc: int) -> None:
    """``out |= src shifted by (dr, dc)`` with hard (non-wrapping) edges."""
    R, C = src.shape
    r0, r1 = max(0, dr), R + min(0, dr)
    c0, c1 = max(0, dc), C + min(0, dc)
    if r0 >= r1 or c0 >= c1:
        return
    out[r0:r1, c0:c1] |= src[r0 - dr:r1 - dr, c0 - dc:c1 - dc]


def dilate_square(mask: np.ndarray, r: int, include_centre: bool) -> np.ndarray:
    """Separable Chebyshev-ball (Moore) dilation - 4r shifts instead of
    (2r+1)^2 - 1."""
    tmp = mask.copy()
    for dc in range(1, r + 1):
        _shift_or(tmp, mask, 0, dc)
        _shift_or(tmp, mask, 0, -dc)
    out = tmp.copy()
    for dr in range(1, r + 1):
        _shift_or(out, tmp, dr, 0)
        _shift_or(out, tmp, -dr, 0)
    if not include_centre:
        out &= ~mask
    return out


def dilate_offsets(mask: np.ndarray, offsets: Sequence[tuple[int, int]]) -> np.ndarray:
    out = np.zeros_like(mask)
    for dr, dc in offsets:
        _shift_or(out, mask, dr, dc)
    return out


def _radius_mask(mask: np.ndarray, r: int, metric: str) -> np.ndarray:
    if metric == "chebyshev":
        return dilate_square(mask, r, include_centre=True)
    if metric == "manhattan":
        return dilate_offsets(mask, spread_offsets("VonNeumann", r)) | mask
    if metric == "euclidean":
        offs = tuple((dr, dc) for dr in range(-r, r + 1) for dc in range(-r, r + 1)
                     if dr * dr + dc * dc <= r * r)
        return dilate_offsets(mask, offs) | mask
    raise ValueError(f"unknown shade_metric {metric!r}")


# ==========================================================================
# Schedule normalisation
# ==========================================================================
def normalise_schedule(schedule: Mapping[str, Any] | None, n_ticks: int,
                       cap: int) -> list[list[tuple[int, int, int]]]:
    """``{"actions":[...]}`` -> per-tick list of ``(plant_index, row, col)``.

    The per-tick cap is applied *by list position* ("only the first 20 in the
    list are applied"), before any validity filtering.  Multiple action entries
    with the same tick are concatenated in list order.
    """
    per_tick: list[list[tuple[int, int, int]]] = [[] for _ in range(n_ticks)]
    if not schedule:
        return per_tick
    for action in schedule.get("actions", ()) or ():
        t = int(action["tick"])
        if not (0 <= t < n_ticks):
            continue
        bucket = per_tick[t]
        for p in action.get("plants", ()) or ():
            if len(bucket) >= cap:
                break
            idx = int(p.get("plant_index", p.get("index")))
            bucket.append((idx, int(p["row"]), int(p["col"])))
    return per_tick


# ==========================================================================
# Simulator
# ==========================================================================
class _Species:
    """Per-species precomputation.  Slot ``s`` indexes the parallel arrays."""

    __slots__ = ("slot", "index", "plant", "offsets", "soil_ok", "ttm",
                 "rate", "rank", "key_index", "key_rank", "no_winter_spread",
                 "no_shade_spread", "no_shade_survival", "shade_radius",
                 "adjacent_shade_penalty", "moore_range", "base_ttm",
                 "base_rate", "base_range", "seeds")

    def __init__(self, slot: int, plant: Plant, world: World, rules: Rules):
        self.slot = slot
        self.index = plant.index
        self.plant = plant
        self.offsets = spread_offsets(plant.spread_type, plant.spread_range,
                                      rules.crosshatch_diagonal_only,
                                      rules.spread_ring_only)
        # Moore dilation is separable: 4r shifts instead of (2r+1)^2-1.
        self.moore_range = (plant.spread_range
                            if plant.spread_type == "Moore"
                            and not rules.spread_ring_only else 0)
        self.base_ttm = plant.time_to_maturity
        self.base_rate = max(1, plant.spread_rate)
        self.base_range = plant.spread_range
        self.seeds = plant.spread_mechanism == "Seeds"
        if rules.soil_filter:
            self.soil_ok = world.soil_mask(plant.preferred_soil)
        else:
            self.soil_ok = world.plantable.copy()
        self.ttm = plant.time_to_maturity if rules.maturity else 0
        self.rate = max(1, plant.spread_rate)
        self.rank = plant.invasiveness_rank
        # Unique tie-break keys.  Larger wins.
        self.key_index = plant.index
        self.key_rank = plant.invasiveness_rank * 1000 + plant.index
        self.no_winter_spread = plant.no_winter_spread
        self.no_shade_spread = plant.no_shade_spread
        self.no_shade_survival = plant.no_shade_survival
        self.shade_radius = plant.shade_radius
        self.adjacent_shade_penalty = plant.adjacent_shade_penalty


def load_context(plant_dataset: str | None = None,
                 classifications: str | None = None,
                 animals_file: str | None = None,
                 unlock_file: str | None = None,
                 unlock_mode: str = "latching",
                 normalise_group_names: bool = False
                 ) -> tuple[Catalogue, Animals, UnlockTracker]:
    """Catalogue + animals + unlock tracker from the static data files.

    Every path is an argument; the defaults only say where the repo keeps them.
    """
    cat = Catalogue.from_files(
        str(plant_dataset or _DATA / "plant_dataset.json"),
        str(classifications or _DATA / "classifications.json"))
    ani = Animals.from_file(str(animals_file or _DATA / "animals.json"), cat,
                            normalise_group_names)
    import json as _json
    with open(str(unlock_file or _DATA / "plant_unlock_conditions.json"),
              "r", encoding="utf-8") as fh:
        unlock_entries = _json.load(fh)
    unl = UnlockTracker(unlock_entries, cat, ani.names, unlock_mode,
                        normalise_group_names)
    return cat, ani, unl


def simulate(world: World,
             plants: Mapping[int, Plant],
             schedule: Mapping[str, Any] | None,
             rules: Rules = Rules(),
             record: Callable[[int, State], None] | None = None,
             n_ticks: int | None = None,
             species: Iterable[int] | None = None,
             context: tuple[Catalogue, Animals, UnlockTracker] | None = None
             ) -> FinalState:
    """Run the world forward and return the final state.

    ``record``, if given, is called as ``record(tick, state)`` after every tick
    completes, with a *live* (not copied) :class:`State`; copy it yourself if
    you want to keep it.

    ``context`` is the (catalogue, animals, unlocks) triple from
    :func:`load_context`.  Pass it to avoid re-reading the static JSON files on
    every rollout; it is rebuilt (and the unlock tracker reset) if omitted.
    """
    R, C = world.rows, world.cols
    T = world.ticks if n_ticks is None else int(n_ticks)
    if rules.inclusive_end:
        T += 1

    cap = rules.max_placements_per_tick
    per_tick = normalise_schedule(schedule, T, cap)

    # --- which species can ever appear ---------------------------------
    if species is not None:
        wanted = sorted({int(s) for s in species})
    else:
        wanted = sorted({p[0] for bucket in per_tick for p in bucket})
    allowed = None if rules.allowed_plants is None else set(rules.allowed_plants)
    specs: list[_Species] = []
    for idx in wanted:  # ascending plant index - deterministic
        if idx not in plants:
            continue
        if allowed is not None and idx not in allowed:
            continue
        specs.append(_Species(len(specs), plants[idx], world, rules))
    S = len(specs)

    slot_of = {sp.index: sp.slot for sp in specs}
    index_of_slot = np.array([sp.index for sp in specs] + [0], dtype=np.int16)

    # --- arrays ---------------------------------------------------------
    sp_arr = np.full((R, C), -1, dtype=np.int8)  # species slot, -1 = empty
    age = np.zeros((R, C), dtype=np.int32)
    nutrient = np.full((R, C), rules.nutrient_start, dtype=np.float32)
    dead_matter = np.zeros((R, C), dtype=bool)

    plantable = world.plantable
    season_table = world.season_table(T)

    any_shade = any(sp.shade_radius > 0 for sp in specs) and rules.shade
    shade = np.zeros((R, C), dtype=bool)
    shade_dirty = True
    shade_src_cache: dict[int, np.ndarray] = {}

    soil_ok_stack = [sp.soil_ok for sp in specs]
    key_index = np.array([sp.key_index for sp in specs], dtype=np.int16)
    key_rank = np.array([sp.key_rank for sp in specs], dtype=np.int16)
    NEG = np.int16(-1)

    comp = rules.competition
    if comp == "rank":
        empty_keys, occ_keys, occ_needs_rank = key_rank, key_rank, True
    elif comp == "last_wins":
        empty_keys, occ_keys, occ_needs_rank = key_index, key_index, False
    else:  # hybrid
        empty_keys, occ_keys, occ_needs_rank = key_index, key_rank, True
    rank_of_slot = np.array([sp.rank for sp in specs] + [0], dtype=np.int32)
    ow_mode = rules.overwrite_mode

    cand = np.zeros((S, R, C), dtype=bool) if S else np.zeros((0, R, C), dtype=bool)
    season = world.initial_season

    # --- Level 2: events, animals, unlocks -------------------------------
    animals_on = (rules.animals_override if rules.animals_override is not None
                  else (rules.animals and world.animals_enabled))
    need_ctx = bool(animals_on or rules.unlocks)
    catalogue = animals_obj = unlocks_obj = None
    if need_ctx:
        if context is None:
            context = load_context(unlock_mode=rules.unlock_mode,
                                   normalise_group_names=rules.normalise_group_names)
        catalogue, animals_obj, unlocks_obj = context
        unlocks_obj.mode = rules.unlock_mode
        unlocks_obj.normalise = rules.normalise_group_names
        animals_obj.normalise = rules.normalise_group_names
        unlocks_obj.reset()

    event_table = (world.events_by_tick(T) if rules.events
                   else [() for _ in range(T)])
    cover_denom = (R * C if rules.coverage_denominator == "all_cells"
                   else int(plantable.sum()))
    # Effective growth parameters, recomputed only when the animal set changes.
    eff_ttm = [sp.ttm for sp in specs]
    eff_rate = [sp.rate for sp in specs]
    eff_offsets = [sp.offsets for sp in specs]
    eff_moore = [sp.moore_range for sp in specs]
    eff_drain = [1.0] * S
    _effect_key: Any = None
    animals_present: tuple[str, ...] = ()
    unlocked_names: tuple[str, ...] = ()
    unlocked_slots: set[int] | None = None
    if unlocks_obj is not None:
        unlocked_names = tuple(unlocks_obj.starters)
    ttm_of_slot = np.array([sp.ttm for sp in specs] + [0], dtype=np.int32)

    def _apply_effects(eff) -> None:
        """Push an animal effect set into the per-species growth parameters."""
        div = rules.effect_rate_semantics == "divide"
        for sp in specs:
            s = sp.slot
            f_rate = eff.factor("spread_rate", sp.index)
            f_mat = eff.factor("maturation_rate", sp.index)
            f_rng = eff.factor("spread_range", sp.index)
            if sp.seeds:
                f_rng *= eff.factor("seed_dispersal", sp.index)
            eff_drain[s] = eff.factor("regression_rate", sp.index)
            if rules.maturity:
                ttm = sp.base_ttm / f_mat if div else sp.base_ttm * f_mat
                eff_ttm[s] = max(0, int(round(ttm)))
            else:
                eff_ttm[s] = 0
            rate = sp.base_rate / f_rate if div else sp.base_rate * f_rate
            eff_rate[s] = max(1, int(round(rate)))
            rng = max(0, int(round(sp.base_range * f_rng)))
            if rng == sp.base_range:
                eff_offsets[s] = sp.offsets
                eff_moore[s] = sp.moore_range
            else:
                eff_offsets[s] = spread_offsets(sp.plant.spread_type, rng,
                                                rules.crosshatch_diagonal_only,
                                                rules.spread_ring_only)
                eff_moore[s] = (rng if sp.plant.spread_type == "Moore"
                                and not rules.spread_ring_only else 0)
            ttm_of_slot[s] = eff_ttm[s]

    def _world_update(t: int) -> None:
        """Counts -> snapshot -> animals -> effects -> unlock set."""
        nonlocal animals_present, unlocked_names, unlocked_slots, _effect_key
        if not need_ctx:
            return
        if S:
            tally = np.bincount(sp_arr[sp_arr >= 0].ravel(), minlength=S)
            counts = {specs[s].index: int(tally[s]) for s in range(S)
                      if tally[s]}
        else:
            counts = {}
        populated = sum(counts.values())
        snap = WorldSnapshot(counts, cover_denom, populated, event_table[t],
                             (), {"dead_matter": int(dead_matter.sum())})
        if animals_on:
            animals_present = animals_obj.present(snap)
            eff = animals_obj.effects_for(animals_present)
            key = eff.key()
            if key != _effect_key:
                _apply_effects(eff)
                _effect_key = key
        if rules.unlocks:
            snap = WorldSnapshot(counts, cover_denom, populated, event_table[t],
                                 animals_present, snap.features)
            unlocked_names = unlocks_obj.evaluate(snap)
            allowed_idx = set(catalogue.indices_for(unlocked_names))
            unlocked_slots = {sp.slot for sp in specs
                              if sp.index in allowed_idx}

    state = State(R, C, world.ticks, -1, np.zeros((R, C), dtype=np.int16),
                  age, nutrient, dead_matter, season, world)

    def _recompute_shade() -> None:
        nonlocal shade, shade_dirty
        srcs = {}
        changed = False
        for sp in specs:
            if sp.shade_radius <= 0:
                continue
            src = sp_arr == sp.slot
            if rules.shade_requires_maturity:
                src &= age >= sp.ttm
            srcs[sp.slot] = src
            old = shade_src_cache.get(sp.slot)
            if old is None or not np.array_equal(old, src):
                changed = True
        if changed:
            new = np.zeros((R, C), dtype=bool)
            for sp in specs:
                if sp.shade_radius <= 0:
                    continue
                src = srcs[sp.slot]
                if src.any():
                    new |= _radius_mask(src, sp.shade_radius, rules.shade_metric)
                shade_src_cache[sp.slot] = src
            shade = new
        shade_dirty = False

    for t in range(T):
        _world_update(t)
        for phase in rules.phase_order:

            # ---------------- season ---------------------------------
            if phase == "season":
                season = season_table[t]

            # ---------------- placements -----------------------------
            elif phase == "placements":
                bucket = per_tick[t]
                if bucket:
                    for idx, r, c in bucket:
                        s = slot_of.get(idx)
                        if s is None:
                            continue  # locked / unknown plant: silently ignored
                        if unlocked_slots is not None and s not in unlocked_slots:
                            continue  # locked plant: silently ignored
                        if not (0 <= r < R and 0 <= c < C):
                            continue
                        if not soil_ok_stack[s][r, c]:
                            continue
                        if rules.require_nutrient_to_enter and nutrient[r, c] <= 0:
                            continue
                        sp_arr[r, c] = s
                        age[r, c] = 0
                        if not rules.dead_matter_persists:
                            dead_matter[r, c] = False
                        shade_dirty = True

            # ---------------- spread ---------------------------------
            elif phase == "spread":
                if not rules.spread or S == 0:
                    continue
                if any_shade and shade_dirty:
                    _recompute_shade()

                occ = sp_arr >= 0
                cand[:] = False
                any_cand = False
                for sp in specs:
                    if rules.season_spread and sp.no_winter_spread \
                            and season == rules.winter_name:
                        continue
                    mine = sp_arr == sp.slot
                    if not mine.any():
                        continue
                    a = age
                    ttm, rate = eff_ttm[sp.slot], eff_rate[sp.slot]
                    if rules.maturity:
                        mine &= a >= ttm
                        if not mine.any():
                            continue
                    if rules.spread_clock == "since_planting":
                        phase_arr = a
                        due = mine & (phase_arr % rate == 0)
                    else:
                        phase_arr = a - ttm
                        due = mine & (phase_arr % rate == 0)
                        if rules.spread_clock == "delayed_maturity":
                            due &= phase_arr >= rate
                    if rules.shade and any_shade and sp.no_shade_spread:
                        due &= ~shade
                    if (rules.shade and any_shade and rules.adjacent_shade_penalty
                            and sp.adjacent_shade_penalty):
                        near = dilate_square(shade, 1, include_centre=True) & ~shade
                        slow = mine & near & (phase_arr % (2 * rate) != 0)
                        due &= ~slow
                    if not due.any():
                        continue
                    if eff_moore[sp.slot]:
                        tgt = dilate_square(due, eff_moore[sp.slot],
                                            include_centre=False)
                    else:
                        tgt = dilate_offsets(due, eff_offsets[sp.slot])
                    tgt &= soil_ok_stack[sp.slot]
                    if rules.same_species_no_replace:
                        tgt &= sp_arr != sp.slot
                    if rules.require_nutrient_to_enter:
                        tgt &= nutrient > 0
                    if tgt.any():
                        cand[sp.slot] = tgt
                        any_cand = True

                if not any_cand:
                    continue

                # ---- competition resolution --------------------------
                ek = np.where(cand, empty_keys[:, None, None], NEG)
                best_e = ek.argmax(axis=0)
                has_e = ek.max(axis=0) >= 0
                if empty_keys is occ_keys:
                    best_o, has_o = best_e, has_e
                else:
                    ok_ = np.where(cand, occ_keys[:, None, None], NEG)
                    best_o = ok_.argmax(axis=0)
                    has_o = ok_.max(axis=0) >= 0

                write_empty = has_e & ~occ
                winner = np.where(write_empty, best_e, best_o)
                take = write_empty.copy()
                # ---- may a spreader displace an existing occupant? ----
                if ow_mode != "never":
                    contest = occ & has_o & (sp_arr != best_o.astype(np.int8))
                    if ow_mode == "always":
                        take |= contest
                    else:
                        by_rank = np.zeros((R, C), dtype=bool)
                        by_seedling = np.zeros((R, C), dtype=bool)
                        if ow_mode in ("rank", "rank_or_immature"):
                            challenger = rank_of_slot[best_o]
                            defender = rank_of_slot[np.where(occ, sp_arr, S)]
                            by_rank = challenger > defender
                        if ow_mode in ("immature_only", "rank_or_immature"):
                            by_seedling = age < ttm_of_slot[np.where(occ, sp_arr, S)]
                        take |= contest & (by_rank | by_seedling)

                if take.any():
                    sp_arr[take] = winner[take].astype(np.int8)
                    age[take] = 0
                    if not rules.dead_matter_persists:
                        dead_matter[take] = False
                    shade_dirty = True

            # ---------------- age ------------------------------------
            elif phase == "age":
                age += (sp_arr >= 0)
                shade_dirty = True

            # ---------------- nutrient -------------------------------
            elif phase == "nutrient":
                if not rules.nutrient_drain:
                    continue
                occ = sp_arr >= 0
                if rules.drain_from_maturity:
                    # "A plant can only begin competing for nutrient capacity in
                    # a cell once it has matured" (problem statement p.5).
                    occ = occ & (age >= ttm_of_slot[np.where(occ, sp_arr, S)])
                if rules.dead_matter_reentry:
                    drain = np.where(dead_matter, rules.drain_dead_matter,
                                     rules.drain_virgin).astype(np.float32)
                else:
                    drain = np.float32(rules.drain_virgin)
                if any(f != 1.0 for f in eff_drain):
                    # animal `regression_rate` scales how fast a plant burns
                    # through a cell's nutrients.  [assumption]
                    per_slot = np.array(eff_drain + [1.0], dtype=np.float32)
                    drain = drain * per_slot[np.where(sp_arr >= 0, sp_arr, S)]
                nutrient -= occ * drain
                if rules.regen_rate:
                    free = ~occ
                    nutrient[free] = np.minimum(nutrient[free] + rules.regen_rate,
                                                rules.regen_cap)

            # ---------------- death ----------------------------------
            elif phase == "death":
                occ = sp_arr >= 0
                if not occ.any():
                    continue
                starved = occ & (nutrient <= 0) if rules.nutrient_drain \
                    else np.zeros((R, C), dtype=bool)
                other = np.zeros((R, C), dtype=bool)
                if rules.shade and rules.shade_kill and any_shade:
                    if shade_dirty:
                        _recompute_shade()
                    for sp in specs:
                        if sp.no_shade_survival:
                            other |= (sp_arr == sp.slot) & shade
                dying = starved | other
                if dying.any():
                    if rules.nutrient_drain:
                        dead_matter |= starved
                        if rules.dead_matter_on_nonnutrient_death:
                            dead_matter |= other
                    sp_arr[dying] = -1
                    age[dying] = 0
                    shade_dirty = True

        if record is not None:
            state.tick = t
            state.grid = index_of_slot[np.where(sp_arr >= 0, sp_arr, S)]
            state.lifespan = age
            state.nutrient = nutrient
            state.dead_matter = dead_matter
            state.season = season
            record(t, state)

    grid = index_of_slot[np.where(sp_arr >= 0, sp_arr, S)]
    return State(R, C, world.ticks, T - 1, grid, age, nutrient, dead_matter,
                 season, world)


# ==========================================================================
# Small conveniences used by experiments / tests
# ==========================================================================
def species_counts(state: State) -> dict[int, int]:
    """``{plant_index: cells}`` for every non-empty species, sorted by index."""
    vals, counts = np.unique(state.grid, return_counts=True)
    return {int(v): int(c) for v, c in zip(vals, counts) if int(v) != 0}


def coverage(state: State) -> int:
    return int((state.grid != 0).sum())


def make_schedule(entries: Iterable[tuple[int, int, int, int]]) -> dict[str, Any]:
    """``[(tick, plant_index, row, col), ...]`` -> submission dict.

    Entries are grouped by tick in ascending tick order; within a tick the
    input order is preserved.
    """
    by_tick: dict[int, list[dict[str, int]]] = {}
    for tick, idx, r, c in entries:
        by_tick.setdefault(int(tick), []).append(
            {"plant_index": int(idx), "row": int(r), "col": int(c)})
    return {"actions": [{"tick": t, "plants": by_tick[t]}
                        for t in sorted(by_tick)]}
