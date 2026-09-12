# State

Cold-start file. Assume the reader has no conversation history.
Update at every checkpoint and before any long operation, then commit.

## Status

Phase 0 complete. Problem extracted into `harness/problem-spec.md`. Repo live on
GitHub. **No simulator exists yet. No submission has been made yet.**

The problem: submit a planting schedule, organisers run their simulator for 500
ticks, only the final tick is scored. We never see intermediate state. All the
risk is in reconstructing their simulator, not in the search.

## Key facts already established (do not re-derive)

- **Level 1 has exactly 5 usable species** — Grass(1), Rose Bush(2), Dwarf
  Sunflower(5), Lavender(6), Oak Tree(12). Verified by computing the unlock
  closure under maximally optimistic assumptions; it is a fixed point at 5. Every
  first-tier unlock needs an animal or a world event, and Level 1 has
  `animals_enabled: false` and zero event commands. **There is no unlock puzzle
  in Level 1.** Do not spend time hunting for one.
- **`N` in `log_N` is 31** (the whole catalogue), stated explicitly in the PDF.
  So Level 1 entropy is capped at `log_31(5) = 0.4687`.
- **Grid 50x50 = 2500 cells; only 1800 are plantable** (dirt 1440 + mud 360).
  Clay (360) is unusable — no starter has soil 2 in `preferred_soil`. Water 180,
  stone 160. Max coverage = **0.72**.
- Seasons: Summer@100, Autumn@200, Winter@300, Spring@400. No events.
- **Nutrients cap plant life at ~100 ticks in a virgin cell.** Scoring reads the
  final tick, so anything planted before ~tick 400 is likely dead at scoring
  time. This is the central trap.

## Best scores

| Level | Local sim score | Verified | Submitted | Leaderboard |
|-------|-----------------|----------|-----------|-------------|
| L1 | — | — | — | — |

Nothing measured yet.

## In flight

Nothing. Awaiting go-ahead on the sub-agent briefs (A simulator, B scorer +
validator, C calibration). D optimiser is blocked until A and B exist.

## Next action

1. Brief sub-agent **B** (scorer + validator) and sub-agent **A** (simulator) in
   parallel — they touch different files (`src/score.py`+`verify.py` vs
   `src/sim.py`).
2. Build the **probe submission** by hand — it does not need the simulator. A
   balanced block of the five species planted across ticks ~400-490, ~360 cells
   each, Oak quarantined in its own corner. Submit it to calibrate alpha, k and
   the leaderboard constant.
3. Then sub-agent **C** runs the calibration experiments listed as open questions
   in `harness/problem-spec.md`.

## Known traps

- `solve.py` / `verify.py` still hold the *practice* reference implementation
  from the old scaffold. Both must be replaced together — a stale verifier will
  happily pass a wrong answer. `benchmarks/cases/` is now empty by design, so CI
  currently runs zero cases and passes trivially.
- `make_submit.py` zips from `git archive`; uncommitted work is silently absent.
- `resources-docs/1(1).json` and `problem-statement(1).pdf` contain parentheses.
  **Quote every shell path** or they break.
- Never hard-code the level filename. Level 2's world file drops into
  `resources-docs/` later; read the path from an argument.
- The PDF contradicts itself on the submission key: worked example says
  `plant_index`, schema block says `index`. We emit `plant_index`.
- The PDF contradicts itself on competition: invasiveness rank vs "last spreader
  wins". Unresolved until tested.
