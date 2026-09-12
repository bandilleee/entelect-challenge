# Entelect Challenge — Photospheria

A planting schedule for the Photospheria ecosystem problem, plus the simulator
it was optimised against.

## The problem in one paragraph

Submit a schedule of `(tick, plant, row, col)` placements. The organisers run
their simulator for T ticks and score **only the final tick**. You never observe
intermediate state. So the work splits in two, and the first half dominates:
reconstruct their simulator well enough to evaluate a candidate schedule
offline, then optimise the schedule against it.

## Run

```
pip install -r requirements.txt

# generate a schedule
python solve.py  --input 'resources-docs/1(1).json' --output answer.json

# validate it (independently of the simulator)
python verify.py --input 'resources-docs/1(1).json' --answer answer.json

# score it against the simulator, across the rules we cannot pin
python experiments/eval_schedule.py 'resources-docs/1(1).json' answer.json

# everything CI runs
./benchmarks/run.sh
python -m pytest tests/ -q
```

## Layout

    solve.py           level -> schedule. No simulation at solve time.
    verify.py          schedule -> valid? Never imports solve or the simulator.
    src/sim.py         the tick loop. Every rule behind a flag on `Rules`.
    src/world.py       level loader. Path is always an argument.
    src/score.py       the published scoring formula, alpha and k as parameters.
    src/render.py      ASCII dump of any tick.
    experiments/       calibration and fitting scripts, each reproducible.
    harness/           problem spec, decisions, experiment log, current state.
    benchmarks/run.sh  solve + verify every level, used by CI.

`verify.py` and `src/score.py` do not import the simulator or the solver — a
test asserts this with an AST check. They are a second opinion, so that a wrong
simulator cannot validate its own output.

## Determinism

Platform rule 6 requires deterministic, reproducible solutions. `solve.py`
contains no RNG and no wall-clock-dependent behaviour, and sorts before
iterating anything set-shaped, because `PYTHONHASHSEED` is not stable across
processes. Output is byte-identical across `PYTHONHASHSEED` 0, 1, 12345 and
99999. The search that *fitted* the constants in `solve.py` lives in
`experiments/`, so solving itself is a fast, pure function of the level file.

## Level 1 approach

Level 1 has exactly five usable species. That is not an assumption: computing
the unlock closure from the five starters under deliberately optimistic
assumptions reaches a fixed point at five, and since the assumptions are an
upper bound the true answer cannot be higher. Every first-tier unlock needs an
animal or a world event, and the level has `animals_enabled: false` and no event
commands. Reproduce with `python experiments/closure.py`.

So there is no unlock puzzle here, and the score reduces to entropy (maximised
when the five species are equal) times coverage, plus a longevity term. Three
things follow, and all three were measured rather than assumed:

1. **Every usable cell gets an explicit placement.** 1800 of the 2500 cells are
   plantable — clay is unusable, since no starter species accepts soil 2 — so
   coverage is pinned at its 0.72 ceiling.
2. **Species are planted in order of exposure time, not invasiveness.** The
   first version ordered by ascending `invasiveness_rank` and scored 0.0023
   worst-case: Grass, which has the *lowest* rank in the catalogue, took 1794 of
   1800 cells. What matters is that whatever is planted earliest has the most
   ticks to spread, and Grass matures in one tick. Sweeping all 120 orderings,
   every one of the top ten plants Grass last.
3. **Seed counts pre-compensate for drift.** Seeding the five equally does not
   finish equal: Sunflower roughly doubles its area while Lavender loses half.
   `SEED_WEIGHTS` is fitted by a damped feedback loop against the simulator.

Two rules in the problem statement are genuinely ambiguous — when a spreading
plant may take an occupied cell, and whether `spread_rate` counts from planting
or from maturity. Rather than bet on a reading, the schedule is optimised for
its **worst case across all six combinations**, and now scores entropy
0.443-0.460 against a 0.4687 ceiling under every one of them.

## Adapting to a new level

Level files are read from an argument, never hard-coded. `solve.py` derives the
plantable set, the region partition and the tick windows from the level, so a
new level file mostly just works; the constants worth refitting are
`PLACEMENT_ORDER` and `SEED_WEIGHTS`, via `experiments/sweep_order.py` and
`experiments/fit_seeds.py`. Mechanics no Level 1 species uses — animals, events,
burnt soil, cracks, coexistence — are parsed but not simulated, and need
building before Level 2.
