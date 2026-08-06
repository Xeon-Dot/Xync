"""FastAPI server for xync."""

from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from xync.config import get_config_dir, load_config
from xync.models import SyncStatus

_api_state: dict = {
    "config_dir": None,
    "sync_status": {},
    "current_mirror": None,
}


def format_size(size_bytes: int) -> str:
    """Convert bytes to human readable size string."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(size_bytes)
    for unit in units:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} EiB"


class MirrorStatusResponse(BaseModel):
    name: str
    enabled: bool
    status: str
    last_sync: Optional[str] = None
    last_size: Optional[int] = None
    size_bytes: int = 0
    size_human: str = "0 B"


class StatusResponse(BaseModel):
    daemon_running: bool = False
    current_mirror: Optional[str] = None
    mirrors: list[MirrorStatusResponse] = []


app = FastAPI(
    title="xync API",
    description="API for monitoring xync mirror synchronization",
    version="0.1.0",
)


@app.get("/api/status")
async def get_status() -> StatusResponse:
    """Get the status of all mirrors."""
    config_dir = _api_state.get("config_dir")
    cfg = load_config(config_dir)
    cfg_dir = get_config_dir(config_dir)

    mirrors_status: list[MirrorStatusResponse] = []
    for name, mirror in cfg.mirrors.items():
        size_bytes = mirror.last_size if mirror.last_size is not None else 0
        live_status = get_sync_status(name).value
        mirrors_status.append(
            MirrorStatusResponse(
                name=name,
                enabled=mirror.enabled,
                status=live_status,
                last_sync=mirror.last_sync.isoformat() if mirror.last_sync else None,
                last_size=mirror.last_size,
                size_bytes=size_bytes,
                size_human=format_size(size_bytes),
            )
        )

    from xync.daemon import get_pid_file, is_running

    pid_file = get_pid_file(cfg_dir)
    daemon_running = is_running(pid_file)

    return StatusResponse(
        daemon_running=daemon_running,
        current_mirror=get_current_mirror(),
        mirrors=mirrors_status,
    )


@app.get("/api/mirrors")
async def list_mirrors() -> list[str]:
    """List all mirror names."""
    config_dir = _api_state.get("config_dir")
    cfg = load_config(config_dir)
    return list(cfg.mirrors.keys())


@app.get("/api/mirrors/{name}")
async def get_mirror_status(name: str):
    """Get status of a specific mirror."""
    config_dir = _api_state.get("config_dir")
    cfg = load_config(config_dir)

    if name not in cfg.mirrors:
        return JSONResponse(
            status_code=404, content={"error": f"Mirror '{name}' not found"}
        )

    mirror = cfg.mirrors[name]
    size_bytes = mirror.last_size if mirror.last_size is not None else 0
    live_status = get_sync_status(name).value

    return MirrorStatusResponse(
        name=name,
        enabled=mirror.enabled,
        status=live_status,
        last_sync=mirror.last_sync.isoformat() if mirror.last_sync else None,
        last_size=mirror.last_size,
        size_bytes=size_bytes,
        size_human=format_size(size_bytes),
    )


@app.get("/api/mirrors/{name}/size")
async def get_mirror_size(name: str):
    """Get the size of a mirror's local directory."""
    config_dir = _api_state.get("config_dir")
    cfg = load_config(config_dir)

    if name not in cfg.mirrors:
        return JSONResponse(
            status_code=404, content={"error": f"Mirror '{name}' not found"}
        )

    mirror = cfg.mirrors[name]
    size_bytes = mirror.last_size if mirror.last_size is not None else 0

    return {
        "name": name,
        "local_path": mirror.local_path,
        "size_bytes": size_bytes,
        "size_human": format_size(size_bytes),
    }


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


def run_api_server(
    host: str = "0.0.0.0", port: int = 58080, pid_file: Optional[Path] = None
) -> None:
    """Run the FastAPI server.

    If *pid_file* is provided, the current PID is written to it on startup
    and the file is removed when the server shuts down.
    """
    import uvicorn

    if pid_file:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
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


def read_api_pid(pid_file: Path) -> Optional[int]:
    """Read the API PID from *pid_file*; return ``None`` if missing or invalid."""
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def is_api_running(pid_file: Path) -> bool:
    """Return ``True`` if the API process recorded in *pid_file* is alive."""
    pid = read_api_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_api(pid_file: Path, force: bool = False) -> bool:
    """Send SIGTERM (or SIGKILL with force=True) to the recorded API process.

    Returns ``True`` if a signal was delivered, ``False`` if the process was
    not found (stale PID file is cleaned up automatically).
    """
    pid = read_api_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False
