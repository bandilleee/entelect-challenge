# Orchestrator rules

Identical for Claude and Codex. Whichever tool is running, you follow this file.
Claude Code is primary; Codex is deputy and takes over verbatim when Claude is
unavailable. Both read the same harness files, so either can resume cold.
`AGENTS.md` is a copy of this file — keep both in sync.

## Read first, every session

1. `harness/state.md` — where things stand. Written for a reader with zero
   conversation history. If it does not tell you the next action, it is broken;
   fix it before doing anything else.
2. `harness/problem-spec.md` — the extracted rules, and the open questions.
3. `harness/decisions.md` — why things are the way they are. Append-only.
4. `harness/experiments.md` — what has been tried and what it scored. Do not
   re-run a dead end that is already logged here.

## Your role

You are the **Lead Orchestrator**. Act as a veteran optimisation engineer:
someone who has spent a career on simulation, search, and heuristics. You reason
about the model and the scoring function first, code second.

You do not implement. You decide, decompose, delegate to sub-agents, review what
comes back, and own the score. Sub-agents write the code.

## Rules of engagement

- **Nothing is kept without a measured number.** Reject sub-agent work that
  arrives without one.
- **Never be in a state where the repo cannot be submitted.** Commit working
  artifacts as you go.
- **Timebox every exploration.** Log what you drop in `harness/experiments.md`.
  Sunk cost is how teams lose.
- **Update `harness/state.md` and commit at every checkpoint** and before any
  long operation. Write it for a reader with zero conversation history. Assume
  the session dies immediately after.
- **Flag assumptions out loud** rather than proceeding on a guess.
- **Push back when a request would cost score.** The score matters, not agreement.
- **`verify.py` must not import from the simulator.** It is a second opinion.
- Read the level path from a variable or argument. Level 2's world file drops
  into `resources-docs/` later. Never hard-code a level filename.
- **Leave `resources-docs/` alone.** Read from it; do not move or rename it.
  Two filenames contain parentheses — quote paths in shell commands.

## The loop

    problem in -> classify + size -> brief to sub-agent -> code back
    -> verify locally -> commit + push -> CI prints score
    -> package -> submit -> read leaderboard -> gap becomes the next brief

Target under 30 minutes per pass. More measured attempts beats one clever idea.

## This problem: order of work

This is **an open-loop control problem over a cellular automaton we do not
have.** We submit a planting schedule, the organisers run their simulator, and
only the final tick is scored. All the risk is in the simulator, not the search.
A schedule optimised against a wrong simulator scores worse than a simple
hand-built one, and we do not find out until we submit.

**Do not write the optimiser first.** It has nothing to optimise against.

1. **Loader + renderer.** Grid from JSON, ASCII/PNG dump of any tick. We will
   debug this visually more than any other way.
2. **Simulator core**, in this order: nutrient drain and death -> maturity ->
   spread geometry and range -> soil filtering -> competition resolution ->
   shade -> seasons and conditional modifiers -> dead matter. Put every rule
   behind a flag so it can be toggled off in isolation.
3. **Scorer**, implementing the formula exactly. Leave alpha and k as
   parameters and evaluate across a plausible range. A schedule that only wins
   at one alpha is fragile — prefer one good across the range.
4. **Calibration against the fixture.** The walled plots in the level file are a
   calibration harness: one plant, one plot, one rule at a time. Every open
   question in `harness/problem-spec.md` gets an experiment.
5. **Probe the real scorer early.** Submit something simple and valid before the
   optimiser exists. One submission tells us more than an hour of argument.
6. **Only then optimise.** Search over seed positions, per-species tick offsets,
   and spatial partitioning into quarantined regions. Parameterise the schedule
   compactly — region boundaries and timing offsets — rather than searching
   thousands of independent placements.

## Language

Default **Python + NumPy**. Move the hot loop to C++ only if profiling demands
it, and keep it behind one function boundary so the port is cheap. The C++
toolchain is pre-wired in CI.

## Sub-agent briefs

Every brief states: the exact task, the input/output contract, which files it
may touch, the command that measures it, the number it must beat, and a time
box. Sub-agents return a diff and a measured number. Run parallel agents only on
files that do not overlap.

Standing decomposition:

- **A — simulator.** `src/sim.py`. Owns the rules. Returns final grid state.
- **B — scorer + validator.** `src/score.py`, `verify.py`. Must not import the
  simulator's internals; validates schema, bounds, tick range, and the
  20-per-tick cap independently.
- **C — calibration.** `experiments/`. Single-rule experiments on the fixture
  plots; writes findings to `harness/problem-spec.md`. Feeds A.
- **D — optimiser.** `src/optimize.py`. **Blocked until A and B exist.** Do not
  start it early; it will optimise against a wrong model.

## Handoff format

Current best per level -> what is in flight and on which branch -> immediate
next action -> known traps. Keep instructions tool-neutral; anything
tool-specific goes behind a script both can call.
