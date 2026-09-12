#!/usr/bin/env python3
"""Scorer + validator tests. Every assertion is hand-computable.

Run:  python -m pytest tests/test_score.py -q
      python tests/test_score.py          (no pytest needed)
"""
from __future__ import annotations

import json
import math
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import score as S            # noqa: E402  src/score.py
import verify as V           # noqa: E402  repo-root verify.py

N = 31                       # catalogue size; asserted below, not assumed
LEVEL = ROOT / "resources-docs" / "1(1).json"


def make_state(rows, cols, ticks, cells):
    """cells: {(r,c): (plant_index, lifespan)}"""
    g = [[0] * cols for _ in range(rows)]
    l = [[0] * cols for _ in range(rows)]
    for (r, c), (sp, life) in cells.items():
        g[r][c] = sp
        l[r][c] = life
    return {"rows": rows, "cols": cols, "ticks": ticks, "grid": g, "lifespan": l}


# --------------------------------------------------------------- catalogue
def test_catalogue_size_is_31():
    assert S.catalogue_size() == 31


# ----------------------------------------------------------------- entropy
def test_single_species_entropy_is_exactly_zero():
    """p=1 => log(1)=0 => H is exactly 0, so main is exactly 0 for any alpha.

    We rely on this: a single-species submission is a pure probe of the
    longevity term, with the 0.8-weighted term provably contributing nothing.
    """
    for count in (1, 7, 100, 2500):
        cells = {(i // 50, i % 50): (1, 100) for i in range(count)}
        st = make_state(50, 50, 500, cells)
        for alpha in (0.0, 0.5, 1.0, 2.0, 7.0):
            b = S.score(st, alpha, 1.0)
            assert b.H == 0.0, (count, alpha, b.H)
            assert b.main == 0.0, (count, alpha, b.main)
            assert b.C == count
            # final is then purely 0.2 * longevity
            assert abs(b.final - 0.2 * b.longevity) < 1e-15


def test_five_species_equal_entropy():
    """5 species at equal proportion => H = log_31(5)."""
    cells = {}
    for i in range(500):
        cells[(i // 50, i % 50)] = ((i % 5) + 1, 100)
    st = make_state(50, 50, 500, cells)
    b = S.score(st, 1.0, 1.0)
    expected = math.log(5) / math.log(N)
    assert abs(b.H - expected) < 1e-12
    assert abs(b.H - 0.46868) < 1e-5
    assert b.C == 500


def test_two_species_equal_entropy():
    """2 species at equal proportion => H = log_31(2)."""
    cells = {}
    for i in range(200):
        cells[(i // 50, i % 50)] = ((i % 2) + 1, 100)
    st = make_state(50, 50, 500, cells)
    b = S.score(st, 1.0, 1.0)
    expected = math.log(2) / math.log(N)
    assert abs(b.H - expected) < 1e-12
    assert abs(b.H - 0.20185) < 1e-5


def test_empty_grid_scores_zero_without_blowing_up():
    st = S.empty_state(50, 50, 500)
    for alpha in (0.0, 0.5, 1.0, 3.0):
        for k in (0.0, 0.5, 1.0, 3.0):
            b = S.score(st, alpha, k)
            assert b.C == 0
            assert b.H == 0.0
            assert b.main == 0.0
            assert b.longevity == 0.0
            assert b.final == 0.0
            assert math.isfinite(b.final)


# --------------------------------------------- fully hand-computed example
def test_hand_computed_small_grid():
    """4x5 grid (C_max=20), T=10, alpha=2, k=3.

    Occupied: (0,0)=sp1 l=10, (0,1)=sp1 l=5, (1,2)=sp2 l=10, (3,4)=sp3 l=0.
      C = 4, counts {1:2, 2:1, 3:1}
      H = -(0.5*log_31 0.5 + 0.25*log_31 0.25 + 0.25*log_31 0.25)
        = (0.5*1 + 0.25*2 + 0.25*2) / log2(31) = 1.5 / log2(31)
      coverage = 4/20 = 0.2 ; ^2 = 0.04
      main = H * 0.04
      longevity = ((10/10)^3 + (5/10)^3 + (10/10)^3 + 0) / 20
                = (1 + 0.125 + 1) / 20 = 2.125/20 = 0.10625
      final = 0.8*main + 0.2*0.10625
    """
    st = make_state(4, 5, 10, {
        (0, 0): (1, 10), (0, 1): (1, 5), (1, 2): (2, 10), (3, 4): (3, 0),
    })
    b = S.score(st, alpha=2.0, k=3.0)

    H = 1.5 / math.log2(31)
    assert b.C == 4
    assert b.C_max == 20
    assert abs(b.coverage - 0.2) < 1e-15
    assert abs(b.coverage_factor - 0.04) < 1e-15
    assert abs(b.H - H) < 1e-12
    assert abs(b.H - 0.30277) < 1e-5
    assert abs(b.main - H * 0.04) < 1e-12
    assert abs(b.longevity - 0.10625) < 1e-12
    assert abs(b.final - (0.8 * H * 0.04 + 0.2 * 0.10625)) < 1e-12
    assert b.species_counts == ((1, 2), (2, 1), (3, 1))


def test_lifespan_on_empty_cell_is_ignored():
    """A stale lifespan under an empty cell must not leak into the score."""
    st = make_state(2, 2, 10, {(0, 0): (1, 10)})
    st["lifespan"][1][1] = 10        # empty cell carrying a lifespan
    b = S.score(st, 1.0, 1.0)
    assert b.C == 1
    assert abs(b.longevity - (1.0 / 4)) < 1e-15


def test_k_zero_does_not_count_empty_cells():
    """0**0 == 1 in IEEE; empty cells must still contribute 0 at k=0."""
    st = make_state(2, 2, 10, {(0, 0): (1, 10)})
    b = S.score(st, 1.0, 0.0)
    assert abs(b.longevity - 0.25) < 1e-15


def test_numpy_and_pure_python_paths_agree():
    st = make_state(4, 5, 10, {
        (0, 0): (1, 10), (0, 1): (1, 5), (1, 2): (2, 10), (3, 4): (3, 0),
    })
    a = S.score(st, 2.0, 3.0)
    saved, S._np = S._np, None
    try:
        b = S.score(st, 2.0, 3.0)
    finally:
        S._np = saved
    assert abs(a.final - b.final) < 1e-12
    assert a.species_counts == b.species_counts
    assert a.C == b.C and abs(a.H - b.H) < 1e-12


def test_sweep_is_deterministic_and_covers_the_grid():
    cells = {}
    for i in range(900):
        cells[(i // 50, i % 50)] = ((i % 5) + 1, 100)
    st = make_state(50, 50, 500, cells)
    s1 = S.sweep(st)
    s2 = S.sweep(st)
    assert s1.rows == s2.rows
    assert len(s1.rows) == len(S.DEFAULT_ALPHAS) * len(S.DEFAULT_KS)
    assert s1.worst <= s1.mean <= s1.best
    assert abs(s1.spread - (s1.best - s1.worst)) < 1e-15


# ------------------------------------------------------------- the verifier
def _level():
    with open(LEVEL, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _plantable_cells(level, soil_wanted=(0, 1), limit=None):
    """Deterministic list of legal (row,col) targets, row-major."""
    terrain, soil, _ = V.build_terrain(level)
    out = []
    for r in range(level["rows"]):
        for c in range(level["cols"]):
            if terrain[r][c] == 0 and soil[r][c] in soil_wanted:
                out.append((r, c))
                if limit and len(out) >= limit:
                    return out
    return out


def _clay_cell(level):
    terrain, soil, _ = V.build_terrain(level)
    for r in range(level["rows"]):
        for c in range(level["cols"]):
            if terrain[r][c] == 0 and soil[r][c] == 2:
                return (r, c)
    raise AssertionError("level has no clay cell")


def _water_cell(level):
    terrain, _, _ = V.build_terrain(level)
    for r in range(level["rows"]):
        for c in range(level["cols"]):
            if terrain[r][c] == 1:
                return (r, c)
    raise AssertionError("level has no water cell")


def _good_schedule(level, n_ticks=5, per_tick=20):
    cells = _plantable_cells(level, limit=n_ticks * per_tick)
    species = [1, 2, 5, 6, 12]
    actions, i = [], 0
    for t in range(n_ticks):
        plants = []
        for _ in range(per_tick):
            r, c = cells[i]
            plants.append({"plant_index": species[i % 5], "row": r, "col": c})
            i += 1
        actions.append({"tick": 490 + t, "plants": plants})
    return {"actions": actions}


def test_valid_schedule_passes():
    lvl = _level()
    ok, cost, problems, rep = V.check(lvl, _good_schedule(lvl))
    assert ok, problems
    assert cost == 100
    assert rep["stats"]["total_placements"] == 100
    assert rep["stats"]["tick_min"] == 490 and rep["stats"]["tick_max"] == 494
    assert len(rep["stats"]["ticks_at_cap"]) == 5
    assert rep["stats"]["per_species"] == {"1": 20, "2": 20, "5": 20, "6": 20, "12": 20}
    assert rep["warnings"] == []


def test_twenty_one_in_a_tick_warns_and_is_strict_invalid():
    lvl = _level()
    ans = _good_schedule(lvl, n_ticks=1, per_tick=21)
    ok, cost, problems, rep = V.check(lvl, ans)
    assert ok                                  # engine truncates, still valid
    assert cost == 20                          # only 20 are applied
    assert rep["stats"]["ticks_over_cap"] == [(490, 21)]
    assert any("SILENTLY" in w for w in rep["warnings"])
    ok2, _, problems2, _ = V.check(lvl, ans, strict=True)
    assert not ok2 and any("cap" in p for p in problems2)


def test_out_of_bounds_is_invalid():
    lvl = _level()
    ans = {"actions": [{"tick": 0, "plants": [
        {"plant_index": 1, "row": 50, "col": 0}]}]}
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("out of bounds" in p for p in problems)


def test_clay_placement_is_invalid():
    lvl = _level()
    r, c = _clay_cell(lvl)
    ans = {"actions": [{"tick": 0, "plants": [
        {"plant_index": 1, "row": r, "col": c}]}]}
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("soil mismatch" in p and "clay" in p for p in problems)


def test_water_placement_is_invalid():
    lvl = _level()
    r, c = _water_cell(lvl)
    ans = {"actions": [{"tick": 0, "plants": [
        {"plant_index": 1, "row": r, "col": c}]}]}
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("water" in p for p in problems)


def test_locked_plant_is_invalid():
    lvl = _level()
    r, c = _plantable_cells(lvl, limit=1)[0]
    ans = {"actions": [{"tick": 0, "plants": [
        {"plant_index": 3, "row": r, "col": c}]}]}   # 3 = Blue Moss, locked
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("LOCKED" in p for p in problems)


def test_unknown_plant_index_is_invalid():
    lvl = _level()
    r, c = _plantable_cells(lvl, limit=1)[0]
    ans = {"actions": [{"tick": 0, "plants": [
        {"plant_index": 99, "row": r, "col": c}]}]}
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("not in plant_dataset" in p for p in problems)


def test_tick_equal_to_T_is_invalid():
    lvl = _level()
    r, c = _plantable_cells(lvl, limit=1)[0]
    ans = {"actions": [{"tick": 500, "plants": [
        {"plant_index": 1, "row": r, "col": c}]}]}
    ok, _, problems, _ = V.check(lvl, ans)
    assert not ok and any("outside [0,499]" in p for p in problems)
    # and 499 is fine
    ans["actions"][0]["tick"] = 499
    assert V.check(lvl, ans)[0]


def test_negative_and_non_integer_tick_is_invalid():
    lvl = _level()
    r, c = _plantable_cells(lvl, limit=1)[0]
    for bad in (-1, 1.5, "3", True):
        ans = {"actions": [{"tick": bad, "plants": [
            {"plant_index": 1, "row": r, "col": c}]}]}
        assert not V.check(lvl, ans)[0], bad


def test_duplicate_placement_warns_but_stays_valid():
    lvl = _level()
    r, c = _plantable_cells(lvl, limit=1)[0]
    pl = {"plant_index": 1, "row": r, "col": c}
    ans = {"actions": [{"tick": 0, "plants": [dict(pl), dict(pl)]}]}
    ok, _, problems, rep = V.check(lvl, ans)
    assert ok, problems
    assert rep["stats"]["duplicate_placements"] == 1
    assert any("duplicate" in w for w in rep["warnings"])


def test_schema_failures():
    lvl = _level()
    for ans in ({}, {"actions": "nope"}, {"actions": [{"tick": 0}]},
                {"actions": [{"tick": 0, "plants": [{"row": 0, "col": 0}]}]},
                {"actions": [{"tick": 0, "plants": [
                    {"index": 1, "row": 0, "col": 0}]}]}):
        assert not V.check(lvl, ans)[0], ans
    # empty schedule is structurally valid (and scores ~nothing)
    assert V.check(lvl, {"actions": []})[0]


def test_cli_round_trip():
    """The CI runner greps the stdout, so exercise the real process."""
    lvl = _level()
    with tempfile.TemporaryDirectory() as d:
        good = pathlib.Path(d) / "good.json"
        good.write_text(json.dumps(_good_schedule(lvl)))
        p = subprocess.run(
            [sys.executable, str(ROOT / "verify.py"), "--input", str(LEVEL),
             "--answer", str(good)], capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "VALID" in p.stdout and "INVALID" not in p.stdout
        assert "COST=100" in p.stdout

        bad = pathlib.Path(d) / "bad.json"
        bad.write_text(json.dumps({"actions": [{"tick": 0, "plants": [
            {"plant_index": 1, "row": 999, "col": 0}]}]}))
        p = subprocess.run(
            [sys.executable, str(ROOT / "verify.py"), "--input", str(LEVEL),
             "--answer", str(bad)], capture_output=True, text=True)
        assert p.returncode == 1
        assert "INVALID" in p.stdout
        assert "out of bounds" in p.stdout


def test_verify_does_not_import_the_simulator():
    """Architectural invariant: a second opinion, not the same code twice."""
    import ast
    banned = {"solve", "sim", "world", "src.sim", "src.world", "src"}
    for path in (ROOT / "verify.py", ROOT / "src" / "score.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names:
                    assert al.name.split(".")[0] not in banned, (path, al.name)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "")
                assert mod not in banned and mod.split(".")[0] not in banned, \
                    (path, mod)


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fails = 0
    for n, f in fns:
        try:
            f()
            print(f"  PASS {n}")
        except Exception as e:                 # noqa: BLE001
            fails += 1
            print(f"  FAIL {n}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
