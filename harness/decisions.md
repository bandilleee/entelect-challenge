# Decisions (append-only — never rewrite history)

## Pre-challenge
- Python + NumPy + OR-Tools as default; C++ pre-wired in CI as the escape hatch.
  Rationale: developer velocity dominates when compute is cheap, and CP-SAT
  absorbs many problem families without bespoke code. Choosing and standing up a
  toolchain on the day would cost an hour we do not have.
- `verify.py` written before any solver, and forbidden from importing `solve.py`.
  Rationale: an invalid answer scores zero; the realistic failure is a malformed
  submission, not a suboptimal one.
- CI kept under three minutes, checking validity and printing cost only.
  Rationale: no pipeline can verify optimality, and a slow pipeline gets skipped.
- Practice problem kept as the rehearsal case, clearly marked as reference only.
  Rationale: proves the loop end to end without implying the real problem shares
  its family.

## 2026-09-12 — Level 1 is a five-species placement problem, not an unlock puzzle

Computed the unlock closure from the five starters under deliberately optimistic
assumptions (every coverage/count threshold assumed reachable, dead_matter
assumed present, animal `species_absent` treated as TRUE). The closure is a fixed
point at **5**. Because the assumptions are an upper bound, the real answer
cannot be higher.

Every first-tier unlock is gated behind an animal `species_present` or a world
event. Level 1 has `animals_enabled: false` and zero event commands — only four
season changes. So no branch of the tree is enterable.

**Consequence:** do not spend any time on unlock strategy in Level 1. The score
is entropy (capped at `log_31(5) = 0.4687`) times coverage (capped at 0.72),
plus a longevity term. Reproduce with `experiments/closure.py`.

## 2026-09-12 — N in log_N is 31, not the level's species count

The PDF defines "N = Total number of species types in the game". Taking N = 5
would have inflated our modelled entropy to 1.0 and made every trade-off wrong.
At N = 31 the Level 1 ceiling is 0.4687, so coverage and longevity carry
relatively more weight than they would otherwise.

## 2026-09-12 — Build the simulator before the optimiser

Only the final tick is scored and we never observe intermediate state. A schedule
optimised against a wrong simulator scores worse than a hand-built one, and the
error is invisible until submission. Sub-agent D (optimiser) is therefore blocked
until A (simulator) and B (scorer/validator) exist and are calibrated.
