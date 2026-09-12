# State

Cold-start file. Assume the reader has no conversation history.
Update at every checkpoint and before any long operation, then commit.

## Status

**Level 1 is done and banked at 274,709,453.** Work has moved to Level 2.

Level 2's world file is `resources-docs/2 (1).json` -- **note the SPACE in the
filename**, where Level 1's `1(1).json` has none. Quote every path.

## Scoring is fully solved -- stop treating these as unknown

From Level 1 submission 1's evaluation log:

    final = 0.8 * H * (C / C_max)  +  0.2 * (1 / C_max) * SUM(l / T)
    alpha = 1      k = 1      N = 31      leaderboard = final * 1e9
    H = -SUM p_i log_31(p_i),  so H = log_31(S) when S species are equal

## Best scores

| Level | Best submitted | Notes |
|-------|----------------|-------|
| L1 | **274,709,453** | submission 1; two later attempts scored worse |
| L2 | not yet submitted | 28 of 31 species reachable, main ceiling ~680M |

### Level 1 -- three real results, and the two theories they killed

| # | placed G/R/S/L/O | ticks | tail | final H | score |
|---|---|---|---|---|---|
| 1 | 351/409/260/553/227 | 407-498 | 2 | 0.4531 | **274,709,453** |
| 2 | 360/360/360/360/360 | 401-490 | 10 | 0.3400 | 209,170,416 |
| 3 | 360/360/360/360/360 | 410-499 | 1 | ~0.373 | 228,005,785 |

- Placements land exactly as written.
- The **tail** -- ticks between the last placement and tick 500 -- is where the
  damage happens. A 2-tick tail moved 10 cells; a 10-tick tail moved 791.
- Redistribution is **strictly ordered by `invasiveness_rank`**, which settles
  the competition ambiguity in the problem statement: rank governs overwriting.
- **Territory size drives expansion.** Submission 1 is the only one that held its
  entropy, and the thing it uniquely had was small territories for the two
  aggressive species (Oak 227, Sunflower 260, against 360 each in the others).
- Chasing the entropy ceiling with equal seeding cost 65M across two
  submissions. **Do not submit a schedule change the simulator cannot first
  reproduce on all three rows above.**

## Level 2 -- why it is a different problem

| | L1 | L2 |
|---|---|---|
| grid | 2500 | **7000** (70x100) |
| animals | off | **on** |
| events | none | **Rain @ 250** |
| usable cells | 1800 | **6135** |
| coverage ceiling | 0.72 | **0.8764** |
| species reachable | 5 | **28** |
| main term ceiling | 270M | **680M** |

**Species count dominates everything.** 5 -> 10 species is worth about +141M,
while every placement lever in all of Level 1 was worth 10-40M.

**Manual placement can no longer fill the grid**: 1980 usable placements against
6135 cells reaches coverage 0.286 against a 0.8764 ceiling. Spread was optional
in Level 1 and is mandatory here, which is exactly why the simulator has to be
calibrated before its output is trusted.

## In flight

Two sub-agents, disjoint files:

- **E -- simulator + calibration.** `src/sim.py`, `src/world.py`,
  `src/animals.py`, `tests/test_sim.py`, `tests/test_animals.py`,
  `experiments/calibrate_l1.py`. Fitting `Rules` to reproduce all three Level 1
  results, then adding animals, events and unlock tracking.
- **F -- Level 2 planner.** `solve.py`, `src/plan.py`, `verify.py`,
  `tests/test_plan.py`, `experiments/plan_l2.py`. Two-phase schedule:
  scaffolding to walk the unlock graph, then the scoring garden ending at 499.

## Next action

1. Review both agents' measured numbers. **Reject anything without one.**
2. Regression-check Level 1: `solve.py` must still emit the 1800-placement,
   ticks 407-498 schedule that scored 274,709,453.
3. Submit Level 2 and read `unlocked_plant_types` and `plant_counts` from the
   evaluation log -- that answers the open question below for free.

## The open question that shapes Level 2

**Do unlocks latch, or are they re-evaluated live?** The condition wording reads
like a live predicate. The current plan assumes **latching**, kept as a one-line
constant so it can be flipped.

- Latching: scaffolding can be disposable, die early, and the late garden still
  places everything.
- Live: prerequisite coverage must survive to tick 500 and competes with the
  garden for space. Much harder, and the schedule changes shape entirely.

The submission log's `unlocked_plant_types` answers it directly. A hedge is
already in place: phase B places species in unlock-dependency order.

## Known traps

- **`resources-docs/2 (1).json` has a space; `1(1).json` does not.** Quote paths.
- The evaluation log is the most informative thing we get -- `plant_counts` for
  all 31 species, plus `entropy`, `main_score`, `longevity_score` and
  `unlocked_plant_types`. Always ask for it after a submission.
- `classifications.json` spells the group `"Shallowroot Species"` while
  `animals.json` requires `"Shallow-root Species"`. Strict matching means
  Rhizorends never appears and Bloodbloom is blocked (28 species); normalising
  gives 29. Worth about 20M.
- Crystal Cactus (Drought) and Phoenix Bloom (Ash Eclipse) need events Level 2
  does not schedule. Permanently blocked; do not plan around them.
- `make_submit.py` zips from `git archive`; uncommitted work is silently absent.
- Our simulator failed to predict all three Level 1 results. Until
  `experiments/calibrate_l1.py` reproduces them, treat its output as a hint.
