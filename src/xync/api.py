"""JSON status API for xync, served with the standard library."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from xync.config import get_config_dir, load_config
from xync.daemon import get_pid_file, is_running
from xync.models import Mirror, SyncStatus
from xync.utils import format_size

_api_state: dict = {
    "config_dir": None,
    "sync_status": {},
    "current_mirror": None,
}


class MirrorNotFoundError(LookupError):
    """Raised by payload helpers when a mirror name is unknown."""


def set_sync_status(mirror_name: str, status: SyncStatus) -> None:
    """Update the sync status for a mirror."""
    _api_state["sync_status"][mirror_name] = status


def get_sync_status(mirror_name: str) -> SyncStatus:
    """Get the current sync status for a mirror."""
    return _api_state["sync_status"].get(mirror_name, SyncStatus.PENDING)


def set_current_mirror(mirror_name: Optional[str]) -> None:
    """Set the currently syncing mirror."""
    _api_state["current_mirror"] = mirror_name


def get_current_mirror() -> Optional[str]:
    """Get the currently syncing mirror."""
    return _api_state.get("current_mirror")


def init_api_state(config_dir: Optional[Path] = None) -> None:
    """Initialize the API state with config directory."""
    _api_state["config_dir"] = config_dir


def _mirror_payload(mirror: Mirror) -> dict:
    """Build the JSON status payload for a single mirror."""
    size_bytes = mirror.last_size or 0
    return {
        "name": mirror.name,
        "enabled": mirror.enabled,
        "status": get_sync_status(mirror.name).value,
        "last_sync": mirror.last_sync.isoformat() if mirror.last_sync else None,
        "size_bytes": size_bytes,
        "size_human": format_size(size_bytes),
    }


def status_payload(config_dir: Optional[Path] = None) -> dict:
    """JSON payload for ``/api/status``."""
    cfg = load_config(config_dir)
    daemon_running = is_running(get_pid_file(get_config_dir(config_dir)))
    return {
        "daemon_running": daemon_running,
        "current_mirror": get_current_mirror(),
        "mirrors": [_mirror_payload(m) for m in cfg.mirrors.values()],
    }


def mirrors_payload(config_dir: Optional[Path] = None) -> list[str]:
    """JSON payload for ``/api/mirrors``."""
    return list(load_config(config_dir).mirrors)


def _get_mirror(name: str, config_dir: Optional[Path] = None) -> Mirror:
    mirror = load_config(config_dir).mirrors.get(name)
    if mirror is None:
        raise MirrorNotFoundError(name)
    return mirror


def mirror_payload(name: str, config_dir: Optional[Path] = None) -> dict:
    """JSON payload for ``/api/mirrors/{name}``."""
    return _mirror_payload(_get_mirror(name, config_dir))


def mirror_size_payload(name: str, config_dir: Optional[Path] = None) -> dict:
    """JSON payload for ``/api/mirrors/{name}/size``."""
    mirror = _get_mirror(name, config_dir)
    payload = _mirror_payload(mirror)
    return {
        "name": name,
        "local_path": mirror.local_path,
        "size_bytes": payload["size_bytes"],
        "size_human": payload["size_human"],
    }


class _Handler(BaseHTTPRequestHandler):
    """Route GET requests to the payload helpers."""

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        mirror_match = re.fullmatch(r"/api/mirrors/([^/]+)(/size)?", path)
        try:
            if path == "/api/status":
                self._send(200, status_payload(_api_state.get("config_dir")))
            elif path == "/api/mirrors":
                self._send(200, mirrors_payload(_api_state.get("config_dir")))
            elif mirror_match:
                name = mirror_match.group(1)
                if mirror_match.group(2):
                    payload = mirror_size_payload(name, _api_state.get("config_dir"))
                else:
                    payload = mirror_payload(name, _api_state.get("config_dir"))
                self._send(200, payload)
            else:
                self._send(404, {"error": "Not found"})
        except MirrorNotFoundError:
            self._send(404, {"error": f"Mirror '{mirror_match.group(1)}' not found"})

    def _send(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def run_api_server(
    host: str = "0.0.0.0", port: int = 58080, pid_file: Optional[Path] = None
) -> None:
    """Run the API server until interrupted.

    If *pid_file* is provided, the current PID is written to it on startup
    and the file is removed when the server shuts down.
    """
    if pid_file:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

    server = ThreadingHTTPServer((host, port), _Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if pid_file:
            pid_file.unlink(missing_ok=True)


def start_api_server_thread(
    host: str = "0.0.0.0", port: int = 58080
) -> threading.Thread:
    """Start the API server in a background thread."""
    thread = threading.Thread(
        target=run_api_server,
        kwargs={"host": host, "port": port},
        daemon=True,
    )
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# API PID file helpers
# ---------------------------------------------------------------------------

_API_PID_FILENAME = "xync-api.pid"


def get_api_pid_file(config_dir: Path) -> Path:
    """Return the path to the API server PID file."""
    return config_dir / _API_PID_FILENAME
