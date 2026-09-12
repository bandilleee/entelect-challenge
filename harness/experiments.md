# Experiments

| # | Level | Approach | Cost | Kept? | Notes |
|---|-------|----------|------|-------|-------|
| 0 | practice L1/L2 | Dijkstra + brute-force stop order | 9 / 60 | reference | Matches published optima. Rehearsal only. |

## 2026-09-12 — Placement ordering: exposure time beats invasiveness rank

**Question.** In what order should the five species be planted?

**Prior belief (wrong).** Ascending `invasiveness_rank`, so the most aggressive
species get the least time to displace a neighbour.

**Method.** All 120 orderings x 6 rule settings (`spread_clock` x `competition`)
x the 36-point (alpha, k) box. `python experiments/sweep_order.py <level> --full`,
67s.

**Result.** The prior belief was worth nothing. Ranked by worst case:

| ordering (early -> late) | worst | mean |
|---|---|---|
| Oak, Rose, Lavender, Sunflower, Grass | **0.1283** | 0.2633 |
| ...every other top-10 entry also ends in Grass | | |
| Grass, Sunflower, Lavender, Rose, Oak | 0.0002 | 0.1920 |

Every one of the top 10 plants Grass **last**; every one of the bottom three
plants it first or second. The driver is exposure time, not rank: the species
planted earliest has the most ticks to spread, and Grass matures in 1 tick
despite having the **lowest** invasiveness rank (1) in the whole catalogue.

**Kept.** `PLACEMENT_ORDER = [12, 2, 6, 5, 1]` in `solve.py`.

## 2026-09-12 — Seed weights: equal seeding does not give an equal finish

**Question.** Entropy is maximised when the five species are equal at tick 500.
Does seeding 360 each achieve that?

**Result.** No. Seeding 360 each finished at Oak 513 / Rose 206 / Lavender 189 /
Sunflower 603 / Grass 255. Sunflower roughly doubles its area, Lavender loses
about half of its own.

**Method.** Damped feedback loop (`experiments/fit_seeds.py`): seed, simulate
across the whole rule matrix, seed the gainers less and the losers more, repeat.
Damping 0.5 because the response is super-linear — shrinking a species' area also
shrinks the frontier it spreads from, so a full correction oscillates.

**Result.** Final counts 330 / 354 / 367 / 301 / 382. Worst case 0.1073 ->
0.1283, mean 0.2392 -> 0.2633.

**Kept.** `SEED_WEIGHTS` in `solve.py`. Fitted against the mean across all six
rule readings, deliberately not against one reading.

## 2026-09-12 — Rule readings we cannot resolve locally

`spread_clock` is the highest-impact unknown. Under `since_maturity` a wavefront
advances one cell per tick regardless of `spread_rate`, which makes that
published field nearly inert — suspicious enough to doubt, but not to rule out.
Under `delayed_maturity` the front advances at 1/`spread_rate` and the field
means something.

Rather than bet, the schedule is optimised for **worst case across all six
readings**. It now scores entropy 0.443-0.460 under every one of them, so the
answer barely depends on which is right. `competition` mode `rank` and `hybrid`
produce byte-identical states on Level 1: they differ only in the empty-cell
tie-break, and the only pair they order differently is Sunflower vs Lavender.

## 2026-09-12 — Level 1: three submissions, and two wrong theories of mine

Ground truth. Every row is a real engine result, not a simulation.

| # | placed (Grass/Rose/Sunf/Lav/Oak) | ticks | tail | final H | score |
|---|---|---|---|---|---|
| 1 | 351 / 409 / 260 / 553 / 227 | 407-498 | 2 | 0.4531 | **274,709,453** |
| 2 | 360 / 360 / 360 / 360 / 360 | 401-490 | 10 | 0.3400 | 209,170,416 |
| 3 | 360 / 360 / 360 / 360 / 360 | 410-499 | 1 | ~0.373 | 228,005,785 |

"tail" = ticks between the last placement and scoring at 500.

**Scoring is fully pinned** (from submission 1's log): `alpha = 1`, `k = 1`,
leaderboard constant `1e9`, `N = 31`, and
`final = 0.8*H*(C/2500) + 0.2*(1/2500)*sum(l/500)`.

**Two theories I held, both wrong:**

1. *"Placements land as placed, so seed equally for maximum entropy."* True only
   for submission 1. Submissions 2 and 3 both redistributed heavily.
2. *"The tail is the only thing that matters, so finish at 499."* Submission 3
   had a **shorter** tail than submission 1 (1 tick vs 2) and still lost 46M.

**What the three rows actually say.** Submission 1 is the only one that held its
entropy, and the thing it uniquely had was **small territories for the two
aggressive species** — Oak 227 and Sunflower 260, against 360 each in the
others. Territory size sets the length of a species' spread frontier, so giving
Oak and Sunflower less ground is what limited their expansion. The fitted
SEED_WEIGHTS were not compensating for phantom drift after all; they were
buying stability, and I removed that protection while trying to chase the
entropy ceiling.

Redistribution is strictly ordered by `invasiveness_rank`, confirmed by
submission 2: Sunflower (4) +534 and Oak (10) +257 gained; Lavender (2) -219,
Rose Bush (2) -252 and Grass (1) -320 lost. **This settles the competition
ambiguity in the problem statement: rank governs overwriting.**

**Standing lesson.** Our simulator did not predict any of the three outcomes,
and neither did my analytic predictor. Three engine logs are now the only
trustworthy ground truth we own, and **no schedule change should be submitted
until the simulator reproduces all three.** Predicting from an uncalibrated
model cost 2 submissions and about 65M.

**Kept for Level 1: submission 1's configuration, 274,709,453.**

## Useful consequence for performance

Only the tail matters for a grid-filling schedule, so a candidate does not need
a 500-tick rollout to evaluate. Seed the grid directly in its placed state and
simulate the last ~15 ticks. That is roughly a 30x cut in rollout cost without
leaving Python, and it should be done before any thought of porting to C++.
