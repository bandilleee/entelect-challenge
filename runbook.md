# Runbook — clean clone to scored submission

    git clone <repo> && cd entelect-challenge
    pip install -r requirements.txt
    ./benchmarks/run.sh                                    # confirm green
    python solve.py --input <level>.json --output answer.json
    python verify.py --input <level>.json --answer answer.json
    git commit -am "level N" && python make_submit.py --level N --answer answer.json

Upload `submissions/levelN.zip` and `submissions/levelN.json`.

## Before every upload
- [ ] `verify.py` run against the exact file being uploaded, not an earlier one
- [ ] work committed (the zip comes from `git archive`)
- [ ] `README.md` present in the zip
- [ ] `harness/state.md` updated and committed

## If a submission fails
Download the platform logs and read them. Do not guess.

## Rehearsal (do this before the day)
Run the loop end to end on the practice cases, then kill the session and resume
from `harness/state.md` alone in the other tool. Whatever breaks, fix now.
