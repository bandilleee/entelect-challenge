#!/usr/bin/env bash
# Solve + verify every level, print validity and placement count per level.
#
# Levels are listed explicitly rather than globbed: level files arrive one at a
# time and two of them have parentheses in the name, so every path is quoted.
# Override with LEVELS="path1 path2" to run a subset.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python

LEVELS=${LEVELS:-"resources-docs/1(1).json"}

fail=0
for level in $LEVELS; do
  if [ ! -f "$level" ]; then
    echo "$level: MISSING (skipped)"
    continue
  fi
  name=$(basename "$level" .json)
  out="/tmp/ans_$name.json"

  if ! "$PY" solve.py --input "$level" --output "$out" 2>"/tmp/err_$name"; then
    echo "$name: SOLVE FAILED"; cat "/tmp/err_$name"; fail=1; continue
  fi

  # Trust verify.py's exit code, not a substring match. "INVALID" contains
  # "VALID", so `grep -q VALID` silently passes every invalid answer.
  result=$("$PY" verify.py --input "$level" --answer "$out" 2>&1)
  status=$?
  cost=$(printf '%s\n' "$result" | grep -o 'COST=[0-9]*' | head -1)

  if [ $status -eq 0 ]; then
    echo "$name: VALID $cost"
  else
    echo "$name: INVALID $cost"
    printf '%s\n' "$result" | sed 's/^/    /'
    fail=1
  fi
done

if [ $fail -eq 0 ]; then echo "--- all levels valid"; else echo "--- FAILURES"; fi
exit $fail
