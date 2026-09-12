# Problem spec — Root Cause Analysis (Photospheria)

Phase 0 extraction. Source: `resources-docs/problem-statement(1).pdf` (21pp) plus
the JSON data files. Everything marked **[V]** was computed from the data in this
repo. Everything marked **[?]** is a reading of the prose and is a hypothesis the
simulator must confirm or kill.

## What this is

Not an optimisation over a static structure. It is an **open-loop control problem
over a cellular automaton we do not have.** We submit a planting schedule, the
organisers run their simulator for T ticks, and score **only the final tick**. We
never observe intermediate state.

## Input format

Level world file, e.g. `resources-docs/1(1).json`. **Read the path from an
argument — level 2 lands in the same folder later.**

```
{ "animals_enabled": bool, "rows": int, "cols": int, "ticks": int,
  "cells": [ {"row":r, "col":c, "terrain":t, "soil":s}, ... ],
  "commands": [ {"type":"season","tick":int,"season":str}, ... ] }
```

- Cells not listed default to `terrain 0, soil 0` (dirt). **[V]**
- Terrain: `0` plantable, `1` water, `2` stone. Prose also names Path and Cracks.
- Soil: `0` Dirt, `1` Mud, `2` Clay, `3` Burnt.

Static data: `plant_dataset.json` (31 plants), `animals.json` (10 animals),
`classifications.json` (species groups), `plant_unlock_conditions.json`.

## Output format (exact schema)

```
{ "actions": [ { "tick": int, "plants": [ {"plant_index":int,"row":int,"col":int}, ... ] } ] }
```

The PDF contradicts itself: the worked example uses `plant_index`, the
"Schema Definition" block uses `index`. **[?] Emit `plant_index` (the worked
example), and confirm on the first submission.**

## Scoring function

```
Final = 0.8 * [ H * (C/C_max)^alpha ]  +  0.2 * [ (1/C_max) * SUM_ij (l_ij/T)^k ]

H     = - SUM_i p_i * log_N(p_i)          0*log_N(0) := 0
p_i   = n_i / C                           n_i = count of species i on the grid
C     = populated cells
C_max = rows * cols   (ALL cells, including water and stone)
l_ij  = lifespan in ticks of the plant on cell (i,j), 0 if empty
alpha, k = undisclosed scaling parameters
```

Final score is then multiplied by a large undisclosed constant for the
leaderboard.

### Three things follow directly from the formula

1. **`N` is 31, the whole catalogue — not the species available in the level.**
   The PDF says "N = Total number of species types in the game". With S species
   in equal proportion, `H = log_31(S)`. So `H` is capped at **log_31(5) =
   0.4687** for Level 1. Unlocking species is the single largest lever in the
   game; Level 1 simply does not offer it (see below).
2. **`C_max` counts unplantable cells.** 2500 here, of which only 1800 can ever
   hold a plant, so the sample-size factor is capped at `0.72^alpha`. **[V]**
3. **Entropy wants exactly equal proportions.** Five species at 360 cells each.
   Any species that runs away toward a monoculture drives H toward zero, so
   **containment is a scoring objective, not a detail.** See the competition
   note below for *which* species is actually the runaway risk — it is not the
   obvious one.

## Hard constraints

- One plant per cell, except plants whose rules allow coexistence
  (`subsurface_growth`, `coexist_all_species`).
- **Max 20 placements per tick; only the first 20 in the list are applied.**
- Ticks are integers in `[0, T-1]`. Scoring is on the final day.
- Coordinates within bounds. Plants only on soil; other terrain uninhabitable.
- Placing onto an occupied cell **replaces** the existing plant.
- Placing a locked plant is silently ignored.

## Level 1 — established from the data

`resources-docs/1(1).json`: 50x50, 500 ticks, `animals_enabled: false`,
1060 listed cells, 4 commands — **all season changes, no events at all**:
Summer@100, Autumn@200, Winter@300, Spring@400. **[V]**

| | cells |
|---|---|
| dirt (soil 0) | 1440 |
| mud (soil 1) | 360 |
| clay (soil 2) | 360 |
| water (180) + stone (160) | 340 |
| **total** | **2500** |

All five starting plants have `preferred_soil: [0,1]`, so **clay is unusable** and
**max coverage is 1800/2500 = 0.72**. **[V]**

The layout is a synthetic fixture: four stone-walled rectangular plots, each a
pure soil type, plus two water boxes. That is not scenery — isolated plots are a
**calibration harness** for controlled single-variable experiments.

### Level 1 is exactly five species — confirmed **[V]**

Computed the unlock closure from the five starters under **maximally optimistic**
assumptions: every coverage/count threshold assumed reachable, `dead_matter`
assumed available, animal `species_absent` treated as TRUE (animals can never
appear when `animals_enabled` is false).

**The closure is a fixed point at 5. Nothing unlocks. All 26 other plants stay
locked.** Because the assumptions are optimistic this is an upper bound, so the
true answer cannot exceed it.

Root cause: every first-tier unlock is gated behind an animal `species_present`
or a world event, and Level 1 has neither. Blue Moss needs Loamcrawlers; Orange
Blossom needs Nectaris or Solwings; Stone Reed needs Virexids; Crimson Vine needs
Nectaris or Canorals; Crystal Cactus needs a Drought event; Mire Bloom needs
Rain. Every deeper plant depends transitively on one of those. There is no
unlock puzzle in Level 1.

**Level 1 is purely placement and timing over five species.**

Reproduce with `experiments/closure.py` (to be committed alongside the sim).

### The five species

| idx | plant | maturity | spread rate | type | range | invasive | weakness / special |
|-----|-------|----------|-------------|------|-------|----------|--------------------|
| 1 | Grass | 1 | 2 | VonNeumann | 1 | 1 | `no_shade_survival` |
| 2 | Rose Bush | 10 | 2 | Row | 1 | 2 | `no_winter_spread` |
| 5 | Dwarf Sunflower | 5 | 4 | CrossHatch | 2 | 4 | `no_shade_spread`, `adjacent_shade_penalty` |
| 6 | Lavender | 4 | 3 | CrossHatch | 1 | 2 | `no_winter_spread` |
| 12 | Oak Tree | 20 | 7 | Moore | 2 | 10 | `shade_radius: 4` |

None of the five has `conditional_modifiers`. **[V]**

### Consequences at five species

- **Oak's shade radius is 4** — a mature Oak shades up to 81 cells. Grass *dies*
  in shade (`no_shade_survival`); Dwarf Sunflower cannot spread in it. **Oak must
  be spatially quarantined**, and its 81-cell shadow is a real cost against the
  coverage term. Oak is nonetheless mandatory: dropping it costs
  `log_31(5) -> log_31(4)`, i.e. 0.469 -> 0.404.
- **Rose Bush and Lavender cannot spread in Winter**, which is ticks 300-400. The
  final 100 ticks are Spring — exactly the window that matters.
- **Competition resolution — the two rules are not in conflict. [?]** The PDF
  looks self-contradictory (p.6 "higher rank wins" vs p.13 "last to spread in
  wins"), but the p.13 text carries its own reconciliation: *"since neither
  plant has reached maturity at that point"*. Best reading:
  - two **seedlings** landing in the same **empty** cell on the same tick ->
    neither is mature, rank cannot apply, **last one in wins**;
  - a **mature** plant pushing into an **occupied** cell -> **invasiveness rank
    decides**.
  This is the highest-priority rule to test, because it inverts the threat
  model. **Grass has `invasiveness_rank: 1` — the lowest of all 31 plants**
  (Rose Bush 2, Lavender 2, Dwarf Sunflower 4, Oak 10). Under this reading Grass
  can fill empty cells fast but can **displace nothing**, while **Oak
  outcompetes all four of the others**. The runaway monoculture risk is
  therefore **Oak, not Grass** — which also compounds with Oak's radius-4 shade
  killing Grass outright. Plan containment around Oak first.
- **20 placements/tick over ticks 400-499 is 2000 placements against 1800 usable
  cells.** Manual placement alone can nearly fill the grid. Spread is an
  accelerant, not a necessity — a useful fallback if spread modelling proves
  unreliable.

### The nutrient clock **[?]**

Cells hold 100 nutrients and lose 1/tick while occupied; at 0 the cell becomes
uninhabitable, the plant dies, and the cell is flagged dead matter. So a plant in
a virgin cell dies roughly 100 ticks after it arrives. **Scoring reads tick 500,
so anything planted before roughly tick 400 is dead at scoring time and
contributes nothing.** The whole game is arranging for a full, balanced grid to
be *alive* at tick 500. A naive entrant plants early and scores an empty garden.

### The dead-matter cycle may double longevity **[?]**

Dead matter regenerates at 1/tick to a cap of 100, and a plant entering a
dead-matter cell drains at **0.5/tick** — so a second generation can live ~200
ticks instead of ~100. If true, the cycle is: plant generation 1 early, let it
die, let the cell regenerate to 100 by ~tick 300, replant, and that plant is
alive at tick 500 with lifespan 200 instead of 100. That doubles the longevity
term. **Highest-value uncertain item in the spec. Test it in isolation, early.**

## Open questions — resolve before trusting any number

1. **[RESOLVED]** `N` in `log_N` is 31, the full catalogue. The PDF says so
   explicitly. Level 1 H is therefore capped at 0.4687.
2. Does `ticks: 500` mean 500 updates, or ticks 0..500 inclusive? An off-by-one
   moves every plant across the life/death boundary at the moment it matters
   most.
3. Within a tick, what is the order of placement, spread, maturation, nutrient
   drain, and death? Every hypothesis above depends on it.
4. Does a plant's lifespan counter reset when it is overwritten by a placement?
5. Is nutrient drain per occupied cell or per plant, and what happens under
   `coexist_all_species`?
6. Do season changes apply before or after that tick's update?
7. Can an ordinary plant spread into a dead-matter cell, or is that exclusive to
   `dead_matter_only_spread` (Glowcap)? Decides whether a self-sustaining wave
   exists.
8. Does `spread_rate` count from planting or from maturity?
9. Is the submission key `plant_index` or `index`?

## Submission mechanics — confirmed off the platform

- Upload is **per level** (tabs for Levels 1-4). Level 1 requires **both a ZIP
  (source) and a JSON (answer)**; the SUBMIT button stays disabled until both
  are attached. `make_submit.py --level 1` already emits exactly this pair.
- **"You can upload multiple versions and manage your submissions below."** No
  per-day cap is stated — only the deadline. **Treat submissions as
  effectively unlimited.** That makes cheap diagnostic submissions worthwhile:
  a calibration ladder costs us nothing but wall-clock.
  - **[?] Unconfirmed: does the leaderboard take our best submission or our
    latest?** If latest, a near-zero diagnostic submission temporarily tanks the
    visible score. Recoverable by resubmitting, but check before firing one.
  - **[?] Unconfirmed: does the platform return a score immediately on upload?**
    The whole calibration plan depends on it. Verify on submission #1.
- Platform's own Level 1 spec: "World Size 50 x 50 / Ticks 500 / Included:
  Seasons, **no animals, no weather conditions**." This **independently confirms
  the five-species closure** — no animals and no events means no unlock branch
  is enterable.

### Solution Validation — a hard constraint on the optimiser

Platform rule 6: *"All solutions need to be deterministic and reproducible. The
solution must produce the same output each time when given the same input."*
Entelect validate submitted solutions, and we ship our source in the ZIP.

**So `solve.py --input <level>.json --output answer.json` must emit a
byte-identical answer on every run, on their machine as well as ours.** This is
an architectural constraint, not a style preference:

- Seed every RNG explicitly (`random`, `numpy.random`). No unseeded sampling.
- **Search must be iteration-bounded, never wall-clock-bounded.** A "run for 60
  seconds" budget produces different answers on different hardware and fails
  rule 6 outright.
- **Beware `PYTHONHASHSEED`.** Iteration order over a `set` of strings is not
  stable across Python processes. Sort before iterating anywhere the order can
  reach the output — tie-breaks in competition resolution and spread order are
  the obvious places.
- No multiprocessing result-ordering dependence.
- Rule 3: submissions are plagiarism-checked. All code is our own.
- Rule 2: individual competition — no team formation.

`make_submit.py` zips from `git archive`, so uncommitted work is silently
absent from the ZIP.

---
## Classification

**Family:** open-loop control / scheduling over a cellular automaton. Not a
classical combinatorial family — there is no closed-form objective, because the
objective is the output of a simulator we must first reconstruct.

**Driving complexity parameter:** not the grid size and not the tick count. It is
**the fidelity of the simulator**. The search space is large but forgiving; model
error is not.

**Band:** exact is impossible. Construct-then-improve, and measure everything.

**Approach:** build the simulator first, calibrate it against the fixture plots,
probe the real scorer with a simple valid schedule early, and only then optimise
a compactly parameterised schedule (region boundaries and per-species timing
offsets) against the simulator.


---

# Level 2 � `resources-docs/2 (1).json`

**Note the filename: `2 (1).json` has a SPACE in it**, where Level 1's `1(1).json`
does not. Quote every path.

| | Level 1 | Level 2 |
|---|---|---|
| grid | 50x50 = 2500 | **70x100 = 7000** |
| ticks | 500 | 500 |
| `animals_enabled` | false | **true** |
| events | none | **Rain @ tick 250** |
| usable cells (soil 0/1) | 1800 | **6135** |
| coverage ceiling | 0.7200 | **0.8764** |
| species reachable | 5 | **28** |
| H ceiling = log_31(S) | 0.4687 | **0.9704** |
| main term ceiling | 0.2700 | **0.6804** |
| as leaderboard points | 270M | **680M** |

Terrain: 5890 dirt, 245 mud, 166 clay, 577+18 water, 104 stone.

## Species count is the whole game now

With scoring pinned at `alpha = k = 1` and `H = log_31(S)`, the marginal value of
one more species at Level 2 coverage is enormous, and front-loaded:

| species | main term | leaderboard | gain |
|---|---|---|---|
| 5 | 0.3286 | 328M | � |
| 10 | 0.4701 | 470M | **+141M** |
| 15 | 0.5529 | 553M | +83M |
| 20 | 0.6117 | 612M | +59M |
| 28 | 0.6804 | 680M | +69M |

For comparison, every placement-tuning lever in the whole of Level 1 was worth
10-40M. **Getting from 5 species to 10 is worth more than all of Level 1.**

## Reachability: 28 of 31 (optimistic upper bound)

`python experiments/closure2.py 'resources-docs/2 (1).json'`

8 of 10 animals become present, which is what opens the graph. The chain starts
from the same five starters: Grass coverage and Rose Bush count trigger
Loamcrawlers and Verdelopes, Lavender triggers Nectaris, and so on.

**Permanently blocked (3):**
- **Crystal Cactus** � needs a `Drought` event. Level 2 schedules only Rain.
- **Phoenix Bloom** � needs an `Ash Eclipse` event. Not scheduled.
- **Bloodbloom** � needs the `Rhizorends` animal (see the data bug below).

### [?] Data bug in their files, worth 1 species (~20M)

`Rhizorends` requires `count(species_group=["Shallow-root Species"]) >= 25`, but
`classifications.json` spells that group **`"Shallowroot Species"`** � no hyphen.
(`"Deep-root Species"` *is* hyphenated and matches fine, so this looks like a
typo on their side rather than a convention.)

- If their engine matches exactly, Rhizorends never appears and Bloodbloom is
  blocked -> **28 species**.
- If it normalises, Rhizorends appears -> **29 species**.

Cheap to settle: plant 25+ shallow-root plants and check whether Bloodbloom
becomes placeable. Not worth blocking on.

## The constraint that reshapes the schedule

**Manual placement can no longer fill the grid.** This is the structural
difference from Level 1:

| | placements | coverage reachable |
|---|---|---|
| ticks 401-499 (virgin cells live ~100 ticks) | 1980 | 0.286 |
| ticks 301-499 (only if dead-matter 0.5 drain is real) | 3980 | 0.571 |
| coverage ceiling | � | **0.8764** |

In Level 1, 1980 placements against 1800 usable cells meant we could hand-place
every cell and ignore spread. Here 1980 placements face 6135 cells. **Spread is
mandatory**, so the spread model we never validated is now load-bearing.

## Consequent shape of a Level 2 schedule

Two phases, because unlocking and scoring want opposite things:

1. **Scaffolding, ticks ~0-400.** Build coverage of the chain plants to trigger
   the animals and walk the unlock graph. These plants are *disposable* � they
   die around 100 ticks after planting and contribute nothing to the final
   score. Their only job is to satisfy thresholds.
2. **Final garden, ticks ~400-499.** Plant the scoring garden: as many of the 28
   species as possible, balanced, seeded so spread fills the grid and everything
   is alive at tick 500.

Open question that decides phase 1's budget: do unlocks, once achieved, **stay**
unlocked when coverage later falls? The conditions read as live predicates
("Checks whether a species exists"), which suggests they may re-lock. If they
re-lock, the scaffolding must survive to tick 500 and competes with the garden
for space � a much harder problem. **Test this early; it changes the entire
structure.**

## Level 1 hard-won facts that carry over

- Placements land exactly as written; the danger is the **tail** between the last
  placement and scoring, during which mature plants overwrite lower-ranked
  neighbours strictly by `invasiveness_rank`.
- Giving an aggressive species less territory limits its spread frontier.
- `alpha = 1`, `k = 1`, leaderboard constant `1e9`, `N = 31`.
