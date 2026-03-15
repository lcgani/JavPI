import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_MAX_STR_LEN = int(os.getenv("JAVPI_BACKEND_MAX_STR_LEN", "400"))
_MAX_ITEMS = int(os.getenv("JAVPI_BACKEND_MAX_ITEMS", "30"))
_MAX_DEPTH = int(os.getenv("JAVPI_BACKEND_MAX_DEPTH", "3"))


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return "<truncated-depth>"

    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= _MAX_ITEMS:
                out["__truncated__"] = f"{len(value) - _MAX_ITEMS} more keys"
                break
            key = str(k)[:64]
            out[key] = _sanitize_value(v, depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [_sanitize_value(v, depth + 1) for v in seq[:_MAX_ITEMS]]
        if len(seq) > _MAX_ITEMS:
            out.append(f"... {len(seq) - _MAX_ITEMS} more items")
        return out

    if isinstance(value, (bytes, bytearray)):
        return f"<{type(value).__name__}:{len(value)} bytes>"

    if isinstance(value, str):
        if len(value) <= _MAX_STR_LEN:
            return value
        return value[:_MAX_STR_LEN] + "...<truncated>"

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    text = str(value)
    if len(text) <= _MAX_STR_LEN:
        return text
    return text[:_MAX_STR_LEN] + "...<truncated>"


class CloudReporter:
    """Non-blocking event reporter for optional Cloud Run backend."""

    def __init__(self, backend_url: str, api_key: str = "", timeout_sec: float = 1.5):
        self.backend_url = backend_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout_sec = float(timeout_sec)
        self.session_id = str(uuid.uuid4())
        self.enabled = True

        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=400)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="javpi-cloud-reporter",
        )
        self._thread.start()

    @classmethod
    def from_env(cls) -> Optional["CloudReporter"]:
        url = os.getenv("JAVPI_BACKEND_URL", "").strip()
        if not url:
            return None
        key = os.getenv("JAVPI_BACKEND_API_KEY", "").strip()
        timeout = float(os.getenv("JAVPI_BACKEND_TIMEOUT_SEC", "1.5"))
        return cls(url, key, timeout)

    def _enqueue(self, method: str, path: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        payload_obj = payload if isinstance(payload, dict) else {"value": payload}
        item = {
            "method": method,
            "path": path,
            "payload": _sanitize_value(payload_obj),
            "attempts": 0,
            "ts": time.monotonic(),
        }
        try:
            self._q.put_nowait(item)
        except queue.Full:
            try:
                _ = self._q.get_nowait()
                self._q.put_nowait(item)
            except Exception:
                pass

    def start_session(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "desktop",
        app_version: str = "0.1.0",
    ) -> None:
        payload = {
            "session_id": self.session_id,
            "source": source,
            "app_version": app_version,
            "metadata": metadata or {},
        }
        self._enqueue("POST", "/v1/sessions/start", payload)

    def event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._enqueue(
            "POST",
            f"/v1/sessions/{self.session_id}/events",
            {
                "type": event_type,
                "payload": payload or {},
                "ts": _utc_now(),
            },
        )

    def tool_event(
        self,
        name: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        elapsed_ms: float,
    ) -> None:
        safe_args = _sanitize_value(dict(args or {}))
        safe_result = _sanitize_value(result or {})
        self.event(
            "tool_call",
            {
                "name": name,
                "args": safe_args,
                "result": safe_result,
                "elapsed_ms": round(float(elapsed_ms), 2),
            },
        )

    def end_session(
        self,
        status: str = "completed",
        summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._enqueue(
            "POST",
            f"/v1/sessions/{self.session_id}/end",
            {
                "status": status,
                "summary": summary or {},
            },
        )

    def close(self, drain_sec: float = 1.0) -> None:
        if not self.enabled:
            return
        end = time.monotonic() + max(0.0, float(drain_sec))
        while (not self._q.empty()) and (time.monotonic() < end):
            time.sleep(0.05)
        self._stop.set()
        try:
            self._thread.join(timeout=0.6)
        except Exception:
            pass

    def _run(self) -> None:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.15)
            except queue.Empty:
                continue

            method = item["method"]
            path = item["path"]
            payload = item["payload"]
            attempts = int(item.get("attempts", 0))

            try:
                url = f"{self.backend_url}{path}"
                if method == "POST":
                    resp = session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout_sec,
                    )
                else:
                    resp = session.get(url, headers=headers, timeout=self.timeout_sec)
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}")
            except Exception:
                if attempts < 2 and not self._stop.is_set():
                    item["attempts"] = attempts + 1
                    try:
                        self._q.put_nowait(item)
                    except queue.Full:
                        pass
                continue
