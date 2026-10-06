"""Small graph helpers. Convention: edge (task, depends_on) means depends_on -> task."""
from __future__ import annotations

from collections import defaultdict, deque


def _adj(nodes, edges):
    adj = {n: [] for n in nodes}
    for task, dep in edges:
        if task in adj and dep in adj:
            adj[dep].append(task)
    return adj


def find_cycle(nodes, edges):
    """Return one cycle as a list of node ids, or None."""
    adj = _adj(nodes, edges)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    for root in adj:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(adj[root]))]
        path = [root]
        color[root] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                path.pop()
            elif color[nxt] == GREY:
                return path[path.index(nxt):] + [nxt]
            elif color[nxt] == WHITE:
                color[nxt] = GREY
                stack.append((nxt, iter(adj[nxt])))
                path.append(nxt)
    return None


def would_create_cycle(nodes, edges, new_edge) -> bool:
    task, dep = new_edge
    if task == dep:
        return True
    adj = _adj(nodes, list(edges))
    seen, queue = {task}, deque([task])  # is `dep` reachable from `task` going forward?
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, []):
            if nxt == dep:
                return True
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def topo_order(nodes, edges):
    """Kahn topological order (stable by node order). Nodes in cycles are appended last."""
    nodes = list(nodes)
    adj = _adj(nodes, edges)
    indeg = defaultdict(int)
    for n in nodes:
        for m in adj[n]:
            indeg[m] += 1
    ready = deque(n for n in nodes if indeg[n] == 0)
    out = []
    while ready:
        n = ready.popleft()
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    out.extend(n for n in nodes if n not in set(out))
    return out
