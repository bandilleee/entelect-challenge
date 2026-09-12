#!/usr/bin/env python3
"""Offline scorer. Predicts what the organisers award for a final state.

Deliberately standalone: this module must NOT import from src/sim.py or
src/world.py. It consumes a plain dict the simulator produces and nothing
else, so that a bug in the simulator cannot hide inside the scorer.

Published formula (harness/problem-spec.md, "Scoring function"):

    Final = 0.8 * [ H * (C/C_max)**alpha ]
          + 0.2 * [ (1/C_max) * SUM_ij (l_ij/T)**k ]

    H     = - SUM_i p_i * log_N(p_i)      with 0*log_N(0) := 0
    p_i   = n_i / C
    C     = number of populated cells
    C_max = rows * cols   (ALL cells, water and stone included)
    T     = ticks
    N     = total species types in the *game catalogue* (31), not the
            number unlocked in the level.

alpha and k are undisclosed, hence `sweep()`.
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Sequence

try:  # optional fast path; the pure-Python fallback is the reference
    import numpy as _np
except ImportError:  # pragma: no cover - CI installs numpy
    _np = None


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PLANT_DATASET = _REPO_ROOT / "resources-docs" / "plant_dataset.json"

#: Plausible ranges for the two undisclosed exponents. Both terms are
#: normalised into [0,1] before exponentiation, so exponents < 1 flatten and
#: exponents > 1 sharpen. 1.0 is the neutral / most likely reading.
DEFAULT_ALPHAS = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0)
DEFAULT_KS = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0)

_catalogue_size_cache: dict[str, int] = {}


def catalogue_size(path: str | pathlib.Path | None = None) -> int:
    """N for log_N: the number of species in the game catalogue.

    Read from plant_dataset.json rather than hard-coded 31 so that a larger
    catalogue in a later level is picked up automatically.
    """
    p = pathlib.Path(path) if path is not None else _PLANT_DATASET
    key = str(p)
    if key not in _catalogue_size_cache:
        with open(p, "r", encoding="utf-8") as fh:
            _catalogue_size_cache[key] = len(json.load(fh))
    return _catalogue_size_cache[key]


@dataclass(frozen=True)
class ScoreBreakdown:
    """Every term separated, so we can see which one is actually moving."""

    final: float          # the number the organisers scale and publish
    main: float           # H * (C/C_max)**alpha          -- weighted 0.8
    longevity: float      # (1/C_max)*SUM (l/T)**k        -- weighted 0.2
    H: float              # Shannon entropy in base N, in [0, log_N(S)]
    C: int                # populated cells
    C_max: int            # rows*cols, unplantable cells included
    coverage: float       # C / C_max  (raw, before **alpha)
    coverage_factor: float  # (C/C_max)**alpha
    N: int                # catalogue size used for log_N
    T: int                # ticks
    alpha: float
    k: float
    species_counts: tuple[tuple[int, int], ...]  # (index, n_i), sorted by index
    mean_lifespan: float  # over populated cells only; 0.0 if C == 0

    # main_weighted + longevity_weighted == final, handy when plotting
    @property
    def main_weighted(self) -> float:
        return 0.8 * self.main

    @property
    def longevity_weighted(self) -> float:
        return 0.2 * self.longevity

    def as_dict(self) -> dict:
        d = asdict(self)
        d["species_counts"] = {str(i): n for i, n in self.species_counts}
        return d

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"final={self.final:.6f}  main={self.main:.6f}(x0.8) "
            f"longevity={self.longevity:.6f}(x0.2)  H={self.H:.6f} "
            f"C={self.C}/{self.C_max} cov={self.coverage:.4f} "
            f"alpha={self.alpha} k={self.k}"
        )


def _entropy_base_n(counts: Sequence[int], total: int, n_species: int) -> float:
    """-SUM p_i log_N(p_i). 0*log_N(0) := 0. Returns 0.0 when total == 0."""
    if total <= 0:
        return 0.0
    log_n = math.log(n_species)
    acc = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            acc -= p * (math.log(p) / log_n)
    # A single species gives exactly -1*log(1) = 0. Clamp -0.0 to 0.0 and kill
    # float dust so that "single species => H is exactly 0" holds literally.
    if acc <= 0.0:
        return 0.0
    return acc


def score(final_state: Mapping, alpha: float, k: float,
          n_species: int | None = None) -> ScoreBreakdown:
    """Score one final state.

    final_state: {"rows":int,"cols":int,"ticks":int,
                  "grid":[[plant_index_or_0,...],...],
                  "lifespan":[[int,...],...]}
    `0` in grid means empty. lifespan on an empty cell is treated as 0
    regardless of what it holds.
    """
    grid = final_state["grid"]
    lifespan = final_state["lifespan"]
    rows = int(final_state.get("rows", len(grid)))
    cols = int(final_state.get("cols", len(grid[0]) if grid else 0))
    T = int(final_state["ticks"])
    N = catalogue_size() if n_species is None else int(n_species)

    if N < 2:
        raise ValueError(f"log_N needs N >= 2, got {N}")
    if T <= 0:
        raise ValueError(f"ticks must be positive, got {T}")

    C_max = rows * cols
    if C_max <= 0:
        raise ValueError(f"C_max must be positive, got rows={rows} cols={cols}")

    if _np is not None:
        g = _np.asarray(grid, dtype=_np.int64)
        life = _np.asarray(lifespan, dtype=_np.float64)
        occupied = g > 0
        C = int(occupied.sum())
        if C:
            bc = _np.bincount(g[occupied])
            idxs = _np.nonzero(bc)[0]
            counts_pairs = tuple((int(i), int(bc[i])) for i in idxs)  # sorted
            counts = [int(bc[i]) for i in idxs]
            live = life[occupied]
            mean_life = float(live.mean())
            # (l/T)**k, with l==0 contributing 0 even at k==0.
            ratio = live / T
            pos = ratio > 0.0
            long_sum = float((ratio[pos] ** k).sum()) if pos.any() else 0.0
        else:
            counts_pairs, counts, mean_life, long_sum = (), [], 0.0, 0.0
    else:
        counter: dict[int, int] = {}
        long_sum = 0.0
        life_total = 0.0
        C = 0
        for r in range(rows):
            grow = grid[r]
            lrow = lifespan[r]
            for c in range(cols):
                sp = grow[c]
                if sp:
                    C += 1
                    counter[sp] = counter.get(sp, 0) + 1
                    l = lrow[c]
                    if l > 0:
                        life_total += l
                        long_sum += (l / T) ** k
        counts_pairs = tuple(sorted(counter.items()))  # sorted: determinism
        counts = [n for _, n in counts_pairs]
        mean_life = (life_total / C) if C else 0.0

    H = _entropy_base_n(counts, C, N)
    coverage = C / C_max
    coverage_factor = coverage ** alpha if coverage > 0.0 else 0.0
    main = H * coverage_factor
    longevity = long_sum / C_max
    final = 0.8 * main + 0.2 * longevity

    return ScoreBreakdown(
        final=final, main=main, longevity=longevity, H=H, C=C, C_max=C_max,
        coverage=coverage, coverage_factor=coverage_factor, N=N, T=T,
        alpha=float(alpha), k=float(k), species_counts=counts_pairs,
        mean_lifespan=mean_life,
    )


@dataclass(frozen=True)
class SweepResult:
    """score() evaluated over a grid of (alpha, k). Use `worst` to rank."""

    rows: tuple[tuple[float, float, float], ...]  # (alpha, k, final), sorted
    best: float
    worst: float
    mean: float
    spread: float          # best - worst
    # The parts that do not depend on alpha/k at all -- cheap sanity read.
    H: float
    C: int
    coverage: float

    def table(self, alphas: Sequence[float], ks: Sequence[float]) -> str:
        """Fixed-width alpha-by-k table. Deterministic ordering."""
        head = "alpha\\k " + "".join(f"{kk:>10.2f}" for kk in ks)
        lut = {(a, kk): v for a, kk, v in self.rows}
        lines = [head]
        for a in alphas:
            lines.append(f"{a:>7.2f} " + "".join(
                f"{lut[(a, kk)]:>10.6f}" for kk in ks))
        lines.append(
            f"best={self.best:.6f} worst={self.worst:.6f} "
            f"mean={self.mean:.6f} spread={self.spread:.6f}")
        return "\n".join(lines)


def sweep(final_state: Mapping,
          alphas: Iterable[float] = DEFAULT_ALPHAS,
          ks: Iterable[float] = DEFAULT_KS,
          n_species: int | None = None) -> SweepResult:
    """Evaluate a state across plausible (alpha, k).

    We want schedules that hold up across the range, not ones that only win
    at one alpha -- rank candidates on `worst` (or `mean`), never on `best`.
    """
    alphas = [float(a) for a in alphas]
    ks = [float(x) for x in ks]
    rows: list[tuple[float, float, float]] = []
    H = C = coverage = None
    for a in alphas:              # explicit loops: deterministic order
        for kk in ks:
            b = score(final_state, a, kk, n_species=n_species)
            rows.append((a, kk, b.final))
            H, C, coverage = b.H, b.C, b.coverage
    finals = [v for _, _, v in rows]
    return SweepResult(
        rows=tuple(rows), best=max(finals), worst=min(finals),
        mean=sum(finals) / len(finals), spread=max(finals) - min(finals),
        H=float(H), C=int(C), coverage=float(coverage),
    )


def empty_state(rows: int, cols: int, ticks: int) -> dict:
    """Convenience for tests and baselines."""
    return {
        "rows": rows, "cols": cols, "ticks": ticks,
        "grid": [[0] * cols for _ in range(rows)],
        "lifespan": [[0] * cols for _ in range(rows)],
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="Score a final-state JSON file.")
    ap.add_argument("state", help="path to a final_state JSON dump")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--k", type=float, default=1.0)
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()
    with open(args.state, "r", encoding="utf-8") as fh:
        st = json.load(fh)
    print(score(st, args.alpha, args.k))
    if args.sweep:
        print(sweep(st).table(DEFAULT_ALPHAS, DEFAULT_KS))
