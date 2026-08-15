import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from .app import build_retriever
from .config import get_settings
from .pipeline import QueryPipeline
from .schemas import QueryRequest


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _latency_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "p50_ms": round(_percentile(ordered, 0.50), 2),
        "p70_ms": round(_percentile(ordered, 0.70), 2),
        "p95_ms": round(_percentile(ordered, 0.95), 2),
        "p100_ms": round(_percentile(ordered, 1.0), 2),
        "mean_ms": round(statistics.mean(values), 2) if values else 0.0,
        "samples": len(values),
    }


async def evaluate(path: Path, mode: str = "retrieval", language: str | None = None) -> dict:
    settings = get_settings()
    retriever = build_retriever()
    pipeline = QueryPipeline(settings, retriever=retriever)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if language:
        rows = [row for row in rows if row.get("language") == language]
    # Warm the retriever/embedder outside the timed window.
    await retriever.search("warmup", "en", settings.retrieval_top_k)

    retrieval_times: list[float] = []
    total_times: list[float] = []
    grounded_ok = 0
    expected_grounded = sum(1 for row in rows if row.get("expected") == "grounded")
    outcomes: list[dict] = []

    for row in rows:
        text = row["query"]
        requested = row.get("language") or None
        started = time.perf_counter()
        if mode == "retrieval":
            citations = await retriever.search(
                text, requested or "en", settings.retrieval_top_k
            )
            retrieval_ms = (time.perf_counter() - started) * 1000
            grounded = bool(citations and max(c.score for c in citations) >= settings.min_retrieval_score)
            total_ms = retrieval_ms
        else:
            response = await pipeline.run(QueryRequest(text=text, language=requested))
            retrieval_ms = response.timings_ms.get("retrieval", 0.0)
            total_ms = response.timings_ms.get("total", retrieval_ms)
            grounded = not response.refused
        retrieval_times.append(retrieval_ms)
        total_times.append(total_ms)
        if row.get("expected") == "grounded" and grounded:
            grounded_ok += 1
        outcomes.append(
            {
                "id": row.get("id"),
                "language": row.get("language") or "en",
                "expected": row.get("expected"),
                "grounded": grounded,
                "retrieval_ms": round(retrieval_ms, 2),
                "total_ms": round(total_ms, 2),
            }
        )

    return {
        "mode": mode,
        "queries": len(rows),
        "expected_grounded": expected_grounded,
        "grounded_ok": grounded_ok,
        "grounding_accuracy": round(grounded_ok / max(1, expected_grounded), 4),
        "retrieval": _latency_summary(retrieval_times),
        "total": _latency_summary(total_times),
        "per_query": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure RAG pipeline latency percentiles")
    parser.add_argument("queries", type=Path)
    parser.add_argument(
        "--mode",
        choices=["retrieval", "end-to-end"],
        default="retrieval",
        help="retrieval measures the orchestration seam (embedding + search + merge); "
        "end-to-end includes hosted STT and answer generation",
    )
    parser.add_argument("--language", help="restrict evaluation to one language code")
    parser.add_argument("--output", type=Path, default=Path("results/latency.json"))
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.queries, mode=args.mode, language=args.language))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
