"""Small bounded graph runner for fixed research workflows.

Routers are ordinary functions, state is a dict, and cycles are explicitly bounded.
The query harness currently uses a linear workflow; this module is ready for parallel
retrieval branches without introducing a heavyweight orchestration framework.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

State = dict[str, object]
NodeFn = Callable[[State], dict[str, object]]
RouteFn = Callable[[State], str]


@dataclass(frozen=True)
class Node:
    name: str
    fn: NodeFn
    max_visits: int = 1


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[str]] = defaultdict(list)
        self.routes: dict[str, tuple[RouteFn, dict[str, str]]] = {}

    def add_node(self, node: Node) -> None:
        if node.name in self.nodes:
            raise ValueError(f"duplicate graph node: {node.name}")
        self.nodes[node.name] = node

    def add_edge(self, source: str, target: str) -> None:
        self.edges[source].append(target)

    def add_router(self, source: str, route: RouteFn, targets: dict[str, str]) -> None:
        self.routes[source] = (route, targets)

    def run(
        self, state: State | None = None, *, start: str, end: str, max_steps: int = 25
    ) -> State:
        current = start
        result = dict(state or {})
        visits: dict[str, int] = defaultdict(int)
        for _ in range(max_steps):
            if current == end:
                return result
            if current not in self.nodes:
                raise ValueError(f"unknown graph node: {current}")
            visits[current] += 1
            node = self.nodes[current]
            if visits[current] > node.max_visits:
                raise RuntimeError(f"node visit limit exceeded: {current}")
            updates = node.fn(result)
            collisions = set(updates) & set(result)
            if collisions:
                raise RuntimeError(f"graph state collision: {sorted(collisions)}")
            result.update(updates)
            if current in self.routes:
                route, targets = self.routes[current]
                try:
                    current = targets[route(result)]
                except KeyError as exc:
                    raise RuntimeError(f"unknown route from {current}") from exc
            elif len(self.edges[current]) == 1:
                current = self.edges[current][0]
            else:
                raise RuntimeError(f"node needs exactly one edge: {current}")
        raise RuntimeError("graph step limit exceeded")
