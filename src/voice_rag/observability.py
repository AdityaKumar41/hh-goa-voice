import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TraceSink:
    """Append-only trace sink; replaceable with an OpenTelemetry adapter later."""

    def __init__(self, path: str = "data/traces.jsonl"):
        self.path = Path(path)
        self._lock = threading.Lock()

    def emit(self, event: str, trace_id: str, **fields: Any) -> None:
        record = {
            "ts": time.time(),
            "event": event,
            "trace_id": trace_id,
            **fields,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.warning("trace sink unavailable", exc_info=True)


def privacy_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
