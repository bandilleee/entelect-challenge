# Entelect Challenge

Solver scaffold. Problem-agnostic by design — the problem-specific code lives in
exactly two functions and everything else stays put.

## Run

    pip install -r requirements.txt
    python solve.py  --input benchmarks/cases/practice-l1/input.json --output answer.json
    python verify.py --input benchmarks/cases/practice-l1/input.json --answer answer.json

## Benchmark everything

    ./benchmarks/run.sh

Each directory under `benchmarks/cases/` holds an `input.json` and an optional
`expect.txt` containing the known cost. Drop a new case in and it is picked up.

## Package a submission

    python make_submit.py --level 1 --answer answer.json

Produces `submissions/level1.zip` (source, from `git archive`) and
`submissions/level1.json` (the answer). Commit before running it — uncommitted
files are not in the zip.

## Layout

    solve.py         input -> answer. Replace solve().
    verify.py        answer -> valid? + cost. Replace check(). Never imports solve.
    make_submit.py   answer + clean-tree source zip
    benchmarks/      cases and the runner
    harness/         state, decisions, experiments, problem spec
    CLAUDE.md        orchestrator rules (AGENTS.md is an identical copy)

## Adapting to a new problem

Replace `solve()` in `solve.py` and `check()` in `verify.py` — both are marked
with `REPLACE FROM HERE`. Add cases under `benchmarks/cases/`. Nothing else
needs to change.

The current bodies are a reference implementation of the practice problem
(shortest path with required stops) so the pipeline is green from commit one.
