#!/usr/bin/env bash
# Solve + verify every case in benchmarks/cases/. Prints one line per case.
# A case is a directory containing input.json and (optionally) expect.txt
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
shopt -s nullglob
for case_dir in benchmarks/cases/*/; do
  name=$(basename "$case_dir")
  input="$case_dir/input.json"
  [ -f "$input" ] || continue
  out="/tmp/ans_$name.json"
  expect_arg=()
  [ -f "$case_dir/expect.txt" ] && expect_arg=(--expect "$(cat "$case_dir/expect.txt")")

  if ! python3 solve.py --input "$input" --output "$out" 2>/tmp/err_$name; then
    echo "$name: SOLVE FAILED"; cat /tmp/err_$name; fail=1; continue
  fi
  result=$(python3 verify.py --input "$input" --answer "$out" "${expect_arg[@]}" 2>&1)
  cost=$(echo "$result" | grep -o 'COST=.*' | head -1)
  if echo "$result" | grep -q VALID; then
    echo "$name: VALID $cost"
  else
    echo "$name: INVALID $cost"; echo "$result" | sed 's/^/    /'; fail=1
  fi
done
[ $fail -eq 0 ] && echo "--- all cases valid" || echo "--- FAILURES"
exit $fail
