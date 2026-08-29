"""In-process latency benchmark surfaced through the API (P50/P70/P95/P100)."""

import statistics
import time

from .harness import ResearchHarness
from .schemas import QueryRequest


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


async def run_benchmark(
    harness: ResearchHarness,
    rows: list[dict],
    answer_mode: str = "fast",
    limit: int = 40,
    warmup: bool = True,
) -> dict:
    """Run up to ``limit`` real queries through the harness and summarize latency.

    Uses the already-warm pipeline (no model reload). In ``fast`` mode this is a
    local retrieve+extract path so the whole benchmark completes in well under a
    second even on the full eval set.
    """
    rows = rows[:limit]
    if warmup:
        await harness.run(QueryRequest(text="Is Hacker House Goa free?", language="en", mode=answer_mode))
    totals: list[float] = []
    retrievals: list[float] = []
    outcomes: list[dict] = []
    for row in rows:
        started = time.perf_counter()
        response = await harness.run(
            QueryRequest(
                text=str(row["query"]),
                language=row.get("language") or "en",
                mode=answer_mode,
            )
        )
        total = (time.perf_counter() - started) * 1000
        retr = response.timings_ms.get("retrieval", 0.0)
        totals.append(total)
        retrievals.append(retr)
        outcomes.append(
            {
                "id": row.get("id"),
                "expected": row.get("expected"),
                "refused": response.refused,
                "grounded": response.grounded,
                "ms": round(total, 1),
            }
        )
    ot = sorted(totals)
    refused_expected = [o for o in outcomes if o["expected"] == "refused"]
    return {
        "mode": answer_mode,
        "queries": len(rows),
        "p50_ms": round(_percentile(ot, 0.50), 1),
        "p70_ms": round(_percentile(ot, 0.70), 1),
        "p95_ms": round(_percentile(ot, 0.95), 1),
        "p100_ms": round(_percentile(ot, 1.0), 1),
        "mean_ms": round(statistics.mean(totals), 1) if totals else 0.0,
        "retrieval_mean_ms": round(statistics.mean(retrievals), 1) if retrievals else 0.0,
        "under_200ms": all(t < 200 for t in totals),
        "refusals_correct": sum(1 for o in refused_expected if o["refused"]) if refused_expected else None,
        "refusals_total": len(refused_expected),
        "outcomes": outcomes,
    }