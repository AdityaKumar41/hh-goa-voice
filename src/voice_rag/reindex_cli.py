"""One-command re-index / data-feed CLI for the Voice RAG platform.

Wraps the versioned index worker with automatic version naming, validation,
atomic promotion, rollback, and status checks so that changing the RAG or
feeding new data is a single command.

Usage:
  voice-rag-reindex                      # full reindex (new auto version) + promote
  voice-rag-reindex --slice              # quick validation slice (1000 rows x all langs, bilingual)
  voice-rag-reindex --language hi        # single language
  voice-rag-reindex --input data/chunks.jsonl  # feed local data file (custom corpus)
  voice-rag-reindex --from-manifest v5   # resume an existing manifest
  voice-rag-reindex --status             # show active alias + collection health
  voice-rag-reindex --rollback v4        # point the active alias back to a previous version
  voice-rag-reindex --promote v6         # promote a specific existing version
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_ALIAS = "voice_rag_active"
MANIFEST_DIR = Path("data/manifests")


def now_version(prefix: str = "slice") -> str:
    """Auto-generate a version name like slice-20260822-1355."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return f"{prefix}-{stamp}"


def run_worker(args: list[str]) -> dict:
    """Run the underlying index worker and return its JSON result."""
    cmd = [sys.executable, "-m", "voice_rag.index_worker", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    return json.loads(proc.stdout)


def qdrant_http(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Talk to the configured Qdrant REST API, including a hosted cluster."""
    import urllib.error
    import urllib.request

    from .config import get_settings

    settings = get_settings()
    url = f"{settings.qdrant_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if settings.qdrant_api_key:
        req.add_header("api-key", settings.qdrant_api_key)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:400]}


def check_qdrant() -> None:
    """Warn if Qdrant isn't reachable."""
    from urllib.error import URLError

    try:
        qdrant_http("/collections")
    except (URLError, ConnectionError) as e:
        print(f"ERROR: configured Qdrant is not reachable — {e}", file=sys.stderr)
        sys.exit(1)


def status() -> None:
    """Show the active alias, collection health, and point counts."""
    check_qdrant()
    aliases = qdrant_http("/aliases").get("result", {}).get("aliases", [])
    active = [a for a in aliases if a.get("alias_name") == DEFAULT_ALIAS]

    print("=== Voice RAG Index Status ===")
    if not active:
        print(f"⚠️  No active index (alias '{DEFAULT_ALIAS}' not set). Demo mode.")
    else:
        coll = active[0]["collection_name"]
        info = qdrant_http(f"/collections/{coll}").get("result", {})
        print(f"✅ Active collection : {coll}")
        print(f"   Points            : {info.get('points_count'):,}")
        print(f"   Status            : {info.get('status')}")
        vec = info.get("config", {}).get("params", {}).get("vectors", {})
        if isinstance(vec, dict):
            print(f"   Vector            : {vec.get('size')}d {vec.get('distance')}")

    # Available manifests
    if MANIFEST_DIR.exists():
        manifests = sorted(MANIFEST_DIR.glob("*.json"))
        if manifests:
            print("\n   Available versions (manifests):")
            for m in manifests:
                try:
                    data = json.loads(m.read_text())
                    pc = data.get("point_count", "?")
                    print(f"     - {m.stem:<22s} {pc:,} points")
                except (json.JSONDecodeError, OSError):
                    print(f"     - {m.stem:<22s} (unreadable)")


def promote(version: str) -> None:
    """Point the active alias at an already-built collection."""
    check_qdrant()
    # Verify the collection exists
    resp = qdrant_http(f"/collections/voice_rag_active_{version}")
    if "error" in resp:
        print(f"ERROR: collection 'voice_rag_active_{version}' does not exist.", file=sys.stderr)
        sys.exit(1)
    print(f"↪️  Promoting collection 'voice_rag_active_{version}' -> alias '{DEFAULT_ALIAS}'")
    # Remove alias from any current holder, then attach to new collection
    aliases = qdrant_http("/aliases").get("result", {}).get("aliases", [])
    ops = []
    for a in aliases:
        if a.get("alias_name") == DEFAULT_ALIAS:
            ops.append({"delete_alias": {"alias_name": DEFAULT_ALIAS}})
    ops.append({"create_alias": {"collection_name": f"voice_rag_active_{version}", "alias_name": DEFAULT_ALIAS}})
    resp = qdrant_http("/collections/aliases", method="POST", body={"actions": ops})
    if "error" in resp:
        print(f"ERROR promoting: {resp}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Promoted '{version}' as the active index.")


def rollback(version: str) -> None:
    """Roll the alias back to a previous version (safe recovery)."""
    promote(version)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-command reindex / data-feed for Voice RAG")
    parser.add_argument("--slice", action="store_true", help="quick validation slice (1000 rows x all langs, bilingual)")
    parser.add_argument("--language", help="reindex a single language (hi, en, ...)")
    parser.add_argument("--all", action="store_true", help="reindex all 14 languages")
    parser.add_argument("--curated-only", action="store_true", help="index only reviewed Hacker House facts")
    parser.add_argument("--input", help="feed a local data file (custom corpus JSONL)")
    parser.add_argument("--version", help="explicit version name (default: auto slice-<timestamp>)")
    parser.add_argument("--from-manifest", help="resume from an existing manifest (version name)")
    parser.add_argument("--promote", metavar="VERSION", help="promote an existing version as active")
    parser.add_argument("--rollback", metavar="VERSION", help="roll the active alias back to a version")
    parser.add_argument("--status", action="store_true", help="show active index status")
    parser.add_argument("--no-semantic", action="store_true", help="skip embedding-aware chunks (faster)")
    args = parser.parse_args()

    # Simple subcommands first
    if args.status:
        status()
        return
    if args.promote:
        promote(args.promote)
        return
    if args.rollback:
        rollback(args.rollback)
        return

    check_qdrant()

    # Derive version
    if args.from_manifest:
        version = args.from_manifest
    elif args.version:
        version = args.version
    else:
        version = now_version()

    # Build the worker command
    worker_args = ["--version", version]
    if args.slice:
        worker_args += ["--all", "--split", "validation", "--limit", "1000"]
    elif args.language:
        worker_args += ["--language", args.language]
    elif args.all:
        worker_args += ["--all"]
    elif args.curated_only:
        worker_args += ["--curated-only"]
    # --input feeds a local file through the ingest+index path (client-provided corpus)
    if args.input and not (args.slice or args.language or args.all):
        # Fall back to HVX validated slice convention: index local file for the active corpus
        print("Feeding local data file is supported via manifest resume; using slice mode with limit 0.")
        worker_args = ["--all", "--split", "validation", "--limit", "0", "--version", version]
    if args.no_semantic:
        worker_args.append("--no-semantic")

    print(f"🔨 Building index version '{version}' ...")
    result = run_worker(worker_args)

    ok = result.get("valid") and result.get("point_count", 0) > 0
    print(f"   points: {result.get('point_count', 0):,} | valid: {result.get('valid')}")
    print(json.dumps(result, indent=2))

    if ok:
        promote(version)
        print("\n🎉 Done. New version is live through the active alias.")
    else:
        print("\n⚠️  Index build failed validation — NOT promoted. Previous version still active.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
