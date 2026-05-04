from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_PARTS = ("api_key", "apikey", "authorization", "token", "secret", "password")


class TraceLogger:
    def __init__(self, output_root: Path, task_id: str, provider: str, session_id: str | None = None):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id = session_id or f"{stamp}-{provider}-{task_id}-{uuid.uuid4().hex[:8]}"
        self.run_id = f"{self.session_id}-{task_id}"
        self.session_dir = output_root / self.session_id
        self.run_dir = self.session_dir / task_id
        self.provider = provider
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "payload": scrub_secrets(payload),
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_json(self, filename: str, payload: dict[str, Any]) -> Path:
        path = self.run_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            json.dump(scrub_secrets(payload), handle, indent=2, ensure_ascii=False, default=str)
        return path


def scrub_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SECRET_PARTS):
                scrubbed[key] = "[REDACTED]"
            else:
                scrubbed[key] = scrub_secrets(child)
        return scrubbed
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    return value
