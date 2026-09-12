#!/usr/bin/env python3
"""Entry point: input file -> answer file.

The body of `solve()` is a REFERENCE IMPLEMENTATION for the practice problem.
It exists so the pipeline is green from commit one and so the whole loop can be
rehearsed end to end. When the real problem lands, replace `solve()` and leave
everything around it alone.

Usage: python solve.py --input <path> --output <path>
"""
import argparse, heapq, itertools, json, pathlib, sys, time


def load(path):
    text = pathlib.Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ============================ REPLACE FROM HERE ============================
def edge_cost(nbr, mode):
    return nbr["weight"] if mode == "weight" else nbr["time"] + nbr["risk"]


def dijkstra(graph, src, mode):
    """Single-source shortest paths. Returns (dist, prev)."""
    dist, prev, seen = {src: 0}, {}, set()
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        for nbr in graph.get(u, []):
            v, nd = nbr["node"], d + edge_cost(nbr, mode)
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def path_between(prev, src, dst):
    out, cur = [dst], dst
    while cur != src:
        cur = prev[cur]
        out.append(cur)
    return out[::-1]


def solve(data, level=None):
    """Shortest path start->end, visiting `stops` in the cheapest order.

    Exact: all-pairs Dijkstra over the terminals, then brute force the
    orderings. Correct for small stop counts; swap in Held-Karp past ~10.
    """
    graph, start, end = data["graph"], data["start"], data["end"]
    stops, mode = data.get("stops", []), data.get("weight", "weight")

    sp = {n: dijkstra(graph, n, mode) for n in [start, *stops]}

    best_cost, best_order = float("inf"), None
    for order in itertools.permutations(stops):
        seq, total = [start, *order, end], 0
        for a, b in zip(seq, seq[1:]):
            total += sp[a][0][b]
            if total >= best_cost:
                break
        else:
            best_cost, best_order = total, order

    route, seq = [start], [start, *best_order, end]
    for a, b in zip(seq, seq[1:]):
        route.extend(path_between(sp[a][1], a, b)[1:])
    return {"route": route}
# ============================= TO HERE =====================================


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--level", default=None)
    a = p.parse_args()
    t0 = time.time()
    answer = solve(load(a.input), a.level)
    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(answer, indent=2))
    print(f"solved in {time.time()-t0:.3f}s -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
