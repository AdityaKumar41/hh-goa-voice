import pytest

from voice_rag.graph import Graph, Node
from voice_rag.release_gate import ReleaseMetrics, evaluate_release


def test_graph_router_and_visit_limit():
    graph = Graph()
    graph.add_node(Node("classify", lambda state: {"intent": "answer"}))
    graph.add_node(Node("answer", lambda state: {"done": True}))
    graph.add_node(Node("refuse", lambda state: {"done": False}))
    graph.add_router(
        "classify", lambda state: state["intent"], {"answer": "answer", "refuse": "refuse"}
    )
    graph.add_edge("answer", "END")
    result = graph.run(start="classify", end="END")
    assert result["done"] is True

    looping = Graph()
    looping.add_node(Node("loop", lambda state: {}, max_visits=2))
    looping.add_router("loop", lambda state: "again", {"again": "loop"})
    with pytest.raises(RuntimeError, match="visit limit"):
        looping.run(start="loop", end="done")


def test_release_gate_requires_all_safety_and_latency_thresholds():
    result = evaluate_release(ReleaseMetrics(0.95, 0.94, 0.88, 120, 0.01))
    assert result.open is True
    failed = evaluate_release(ReleaseMetrics(0.95, 0.94, 0.88, 220, 0.01))
    assert failed.open is False
    assert failed.failures == ("p70_retrieval_ms",)
