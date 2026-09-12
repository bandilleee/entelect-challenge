#!/usr/bin/env python3
"""Independent checker. Written before the solver, on purpose.

An invalid answer scores zero, so this is the file that protects the day.
It must NOT import from solve.py -- the point is a second opinion, not the
same code run twice. `check()` below is the reference implementation for the
practice problem; replace it alongside solve().

Usage: python verify.py --input <path> --answer <path> [--expect <cost>]
Exit 0 = valid, 1 = invalid. Prints COST=<n> for CI to pick up.
"""
import argparse, json, pathlib, sys


def load(path):
    text = pathlib.Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ============================ REPLACE FROM HERE ============================
def check(data, answer):
    """Return (ok, cost, problems).

    Deliberately paranoid. Every check here maps to a way of scoring zero.
    """
    problems = []

    if not isinstance(answer, dict) or "route" not in answer:
        return False, None, ["answer must be an object with a 'route' key"]
    route = answer["route"]
    if not isinstance(route, list) or not route:
        return False, None, ["'route' must be a non-empty list"]
    if not all(isinstance(n, str) for n in route):
        return False, None, ["route entries must be strings"]

    graph, start, end = data["graph"], data["start"], data["end"]
    stops, mode = data.get("stops", []), data.get("weight", "weight")

    unknown = [n for n in route if n not in graph]
    if unknown:
        problems.append(f"nodes not in graph: {sorted(set(unknown))}")
    if route[0] != start:
        problems.append(f"route starts at {route[0]!r}, expected {start!r}")
    if route[-1] != end:
        problems.append(f"route ends at {route[-1]!r}, expected {end!r}")

    missing = [s for s in stops if s not in route]
    if missing:
        problems.append(f"required stops missing: {missing}")

    # Contiguity: every consecutive pair must be a real edge. Repeated nodes
    # are legal -- concatenated legs revisit intermediates all the time.
    cost = 0
    for a, b in zip(route, route[1:]):
        if a not in graph:
            continue
        match = next((n for n in graph[a] if n["node"] == b), None)
        if match is None:
            problems.append(f"no edge {a} -> {b}")
            continue
        cost += match["weight"] if mode == "weight" else match["time"] + match["risk"]

    return (not problems), (None if problems else cost), problems
# ============================= TO HERE =====================================


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--answer", required=True)
    p.add_argument("--expect", type=float, default=None)
    a = p.parse_args()

    ok, cost, problems = check(load(a.input), load(a.answer))
    for m in problems:
        print(f"  ! {m}")
    print(f"COST={cost}")
    if not ok:
        print("INVALID", file=sys.stderr); sys.exit(1)
    if a.expect is not None and cost != a.expect:
        print(f"MISMATCH: expected {a.expect}, got {cost}", file=sys.stderr); sys.exit(1)
    print("VALID")


if __name__ == "__main__":
    main()
