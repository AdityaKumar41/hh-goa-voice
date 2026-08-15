from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseMetrics:
    grounded_rate: float
    refusal_precision: float
    retrieval_recall: float
    p70_retrieval_ms: float
    error_rate: float


@dataclass(frozen=True)
class GateResult:
    open: bool
    failures: tuple[str, ...]


def evaluate_release(metrics: ReleaseMetrics) -> GateResult:
    """Deterministic promotion contract; judge scores are inputs, never control flow."""
    checks = {
        "grounded_rate": metrics.grounded_rate >= 0.90,
        "refusal_precision": metrics.refusal_precision >= 0.90,
        "retrieval_recall": metrics.retrieval_recall >= 0.80,
        "p70_retrieval_ms": metrics.p70_retrieval_ms < 200,
        "error_rate": metrics.error_rate <= 0.02,
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    return GateResult(open=not failures, failures=failures)
