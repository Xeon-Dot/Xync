"""xync — Linux mirror synchronization and management CLI."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Annotated, Optional, Union, get_args, get_origin

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from xync.config import get_config_dir, get_config_path, load_config, save_config
from xync.models import GlobalConfig, Mirror, MirrorType, SyncStatus, xyncConfig
from xync.notify import send_test_notification
from xync.sync import SyncResult, diff_mirror, run_sync_batch
from xync.utils import disk_usage_for_path, format_size

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    """Configure basic logging for the xync package.

    Sends WARNING and above to stderr with a minimal format.  When the
    daemon runs, stderr is redirected to the daemon log file.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    logging.getLogger("xync").addHandler(handler)
    logging.getLogger("xync").setLevel(logging.WARNING)


_setup_logging()

app = typer.Typer(
    name="xync",
    help="Linux mirror synchronization and management CLI.",
    add_completion=True,
    no_args_is_help=True,
)
mirror_app = typer.Typer(help="Manage mirror configurations.", no_args_is_help=True)
config_app = typer.Typer(help="Manage global xync configuration.", no_args_is_help=True)
daemon_app = typer.Typer(
    help="Manage the background sync daemon.", no_args_is_help=True
)
api_app = typer.Typer(help="Manage the API server.", no_args_is_help=True)
notify_app = typer.Typer(help="Test notification channels.", no_args_is_help=True)

app.add_typer(mirror_app, name="mirror")
app.add_typer(config_app, name="config")
app.add_typer(daemon_app, name="daemon")
app.add_typer(api_app, name="api")
app.add_typer(notify_app, name="notify")

console = Console()

# ---------------------------------------------------------------------------
# Shared option
# ---------------------------------------------------------------------------

ConfigDirOption = Annotated[
    Optional[Path],
    typer.Option(
        "--config-dir",
        "-C",
        help="Path to xync configuration directory.",
        envvar="xync_CONFIG_DIR",
        show_default=False,
    ),
]

# ---------------------------------------------------------------------------
# xync init
# ---------------------------------------------------------------------------


@app.command()
def init(
    config_dir: ConfigDirOption = None,
) -> None:
    """Initialise the xync configuration directory."""
    cfg_dir = get_config_dir(config_dir)
    cfg_path = get_config_path(config_dir)

    if cfg_path.exists():
        rprint(f"[yellow]Configuration already exists at[/yellow] {cfg_path}")
        return

    cfg = xyncConfig()
    save_config(cfg, config_dir)
    rprint(f"[green]✓ Initialised xync configuration at[/green] {cfg_dir}")


# ---------------------------------------------------------------------------
# xync mirror add
# ---------------------------------------------------------------------------


@mirror_app.command("add")
def mirror_add(
    name: Annotated[str, typer.Argument(help="Unique mirror name (slug).")],
    url: Annotated[
        str, typer.Argument(help="Source URL (rsync://, http://, https://, ftp://).")
    ],
    local_path: Annotated[str, typer.Argument(help="Local destination directory.")],
    mirror_type: Annotated[
        MirrorType,
        typer.Option("--type", "-t", help="Sync protocol."),
    ] = MirrorType.RSYNC,
    description: Annotated[
        str, typer.Option("--description", "-d", help="Short description.")
    ] = "",
    bandwidth_limit: Annotated[
        Optional[str],
        typer.Option("--bwlimit", "-b", help="Bandwidth limit for rsync (e.g. '10m')."),
    ] = None,
    rsync_opts: Annotated[
        Optional[str],
        typer.Option(
            "--rsync-opts",
            help="Space-separated rsync options (overrides defaults, e.g. '-avz --delete').",  # noqa: E501
        ),
    ] = None,
    config_dir: ConfigDirOption = None,
) -> None:
    """Add a new mirror to the configuration."""
    cfg = load_config(config_dir)

    if name in cfg.mirrors:
        rprint(f"[red]Error:[/red] Mirror [bold]{name}[/bold] already exists.")
        raise typer.Exit(1)

    rsync_options = (
        rsync_opts.split() if rsync_opts else cfg.global_config.default_rsync_options
    )

    try:
        mirror = Mirror(
            name=name,
            url=url,
            local_path=local_path,
            mirror_type=mirror_type,
            description=description,
            bandwidth_limit=bandwidth_limit,
            rsync_options=rsync_options,
        )
    except ValueError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    cfg.mirrors[name] = mirror
    save_config(cfg, config_dir)
    rprint(f"[green]✓ Added mirror[/green] [bold]{name}[/bold]  →  {url}")


# ---------------------------------------------------------------------------
# xync mirror remove
# ---------------------------------------------------------------------------


@mirror_app.command("remove")
def mirror_remove(
    name: Annotated[str, typer.Argument(help="Mirror name to remove.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
    config_dir: ConfigDirOption = None,
) -> None:
    """Remove a mirror from the configuration."""
    cfg = load_config(config_dir)

    if name not in cfg.mirrors:
        rprint(f"[red]Error:[/red] Mirror [bold]{name}[/bold] not found.")
        raise typer.Exit(1)

    if not yes:
        typer.confirm(f"Remove mirror '{name}'?", abort=True)

    del cfg.mirrors[name]
    save_config(cfg, config_dir)
    rprint(f"[green]✓ Removed mirror[/green] [bold]{name}[/bold]")


# ---------------------------------------------------------------------------
# xync mirror list
# ---------------------------------------------------------------------------


@mirror_app.command("list")
def mirror_list(
    config_dir: ConfigDirOption = None,
) -> None:
    """List all configured mirrors."""
    cfg = load_config(config_dir)

    if not cfg.mirrors:
        rprint(
            "[yellow]No mirrors configured.[/yellow]  Run [bold]xync mirror add[/bold] to add one."  # noqa: E501
        )
        return

    table = Table(title="Configured Mirrors", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("URL")
    table.add_column("Local Path")
    table.add_column("Enabled")
    table.add_column("Last Status")
    table.add_column("Last Sync")

    for mirror in cfg.mirrors.values():
        status_style = _status_style(mirror.last_status)
        table.add_row(
            mirror.name,
            mirror.mirror_type.value,
            mirror.url,
            mirror.local_path,
            "[green]✓[/green]" if mirror.enabled else "[red]✗[/red]",
            f"[{status_style}]{mirror.last_status.value}[/{status_style}]",
            mirror.last_sync.strftime("%Y-%m-%d %H:%M UTC")
            if mirror.last_sync
            else "—",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# xync mirror show
# ---------------------------------------------------------------------------


@mirror_app.command("show")
def mirror_show(
    name: Annotated[str, typer.Argument(help="Mirror name.")],
    config_dir: ConfigDirOption = None,
) -> None:
    """Show detailed information about a single mirror."""
    cfg = load_config(config_dir)
    mirror = _get_mirror(cfg, name)

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    rows = [
        ("Name", mirror.name),
        ("Description", mirror.description or "—"),
        ("URL", mirror.url),
        ("Local Path", mirror.local_path),
        ("Type", mirror.mirror_type.value),
        ("Enabled", "yes" if mirror.enabled else "no"),
        ("Rsync Options", " ".join(mirror.rsync_options)),
        ("HTTP Options", " ".join(mirror.http_options) if mirror.http_options else "—"),
        ("Bandwidth Limit", mirror.bandwidth_limit or "—"),
        ("Last Sync", mirror.last_sync.isoformat() if mirror.last_sync else "—"),
        ("Last Status", mirror.last_status.value),
    ]
    for key, value in rows:
        table.add_row(key, value)

    console.print(table)


# ---------------------------------------------------------------------------
# xync mirror enable / disable
# ---------------------------------------------------------------------------


@mirror_app.command("enable")
def mirror_enable(
    name: Annotated[str, typer.Argument(help="Mirror name.")],
    config_dir: ConfigDirOption = None,
) -> None:
    """Enable a mirror."""
    _set_mirror_enabled(name, True, config_dir)


@mirror_app.command("disable")
def mirror_disable(
    name: Annotated[str, typer.Argument(help="Mirror name.")],
    config_dir: ConfigDirOption = None,
) -> None:
    """Disable a mirror (skip during sync)."""
    _set_mirror_enabled(name, False, config_dir)


def _set_mirror_enabled(name: str, enabled: bool, config_dir: Optional[Path]) -> None:
    cfg = load_config(config_dir)
    mirror = _get_mirror(cfg, name)
    mirror.enabled = enabled
    cfg.mirrors[name] = mirror
    save_config(cfg, config_dir)
    state = "enabled" if enabled else "disabled"
    rprint(f"[green]✓[/green] Mirror [bold]{name}[/bold] {state}.")


# ---------------------------------------------------------------------------
# xync mirror diff
# ---------------------------------------------------------------------------


@mirror_app.command("diff")
def mirror_diff(
    name: Annotated[str, typer.Argument(help="Mirror name.")],
    config_dir: ConfigDirOption = None,
) -> None:
    """Show rsync dry-run diff for a mirror (what would change)."""
    cfg = load_config(config_dir)
    mirror = _get_mirror(cfg, name)

    try:
        output = diff_mirror(mirror)
    except (ValueError, FileNotFoundError) as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if not output.strip():
        rprint("[dim]No changes.[/dim]")
    else:
        print(output)


# ---------------------------------------------------------------------------
# xync sync
# ---------------------------------------------------------------------------


@app.command()
def sync(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Mirror name(s) to sync. Omit to sync all enabled mirrors."
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", "-n", help="Print the sync command without executing it."
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Print subprocess output to console."),
    ] = False,
    config_dir: ConfigDirOption = None,
) -> None:
    """Sync one or more mirrors."""
    cfg = load_config(config_dir)
    cfg_dir = get_config_dir(config_dir)
    log_dir_base = (
        Path(cfg.global_config.log_dir)
        if cfg.global_config.log_dir
        else cfg_dir / "logs"
    )

    targets = _resolve_sync_targets(cfg, names)
    if not targets:
        rprint("[yellow]No mirrors to sync.[/yellow]")
        return

    if dry_run:
        any_failure = False
        for mirror in targets:
            rprint(
                f"\n[bold cyan]Syncing[/bold cyan] [bold]{mirror.name}[/bold]  ({mirror.url})"  # noqa: E501
            )
            from xync.sync import _build_command

            try:
                cmd = _build_command(mirror, check_tools=False)
                rprint(f"  [dim]dry-run command:[/dim] {' '.join(cmd)}")
            except (FileNotFoundError, ValueError) as exc:
                rprint(f"  [red]Could not build command:[/red] {exc}")
                any_failure = True
        if any_failure:
            raise typer.Exit(1)
        return

    def _report(mirror: Mirror, result: SyncResult) -> None:
        style = _status_style(result.status)
        rprint(
            f"\n[bold cyan]Syncing[/bold cyan] "
            f"[bold]{mirror.name}[/bold]  ({mirror.url})"
        )
        rprint(
            f"  [{style}]{result.status.value.upper()}[/{style}]  "
            f"({result.duration_seconds:.1f}s)  "
            f"log → {result.log_path}"
        )
        if result.error:
            rprint(f"  [red]Error:[/red] {result.error}")

    if run_sync_batch(
        cfg, config_dir, log_dir_base, targets, verbose=verbose, report=_report
    ):
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# xync status
# ---------------------------------------------------------------------------


@app.command()
def status(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(help="Mirror name(s). Omit to show all."),
    ] = None,
    config_dir: ConfigDirOption = None,
) -> None:
    """Show sync status of mirrors."""
    cfg = load_config(config_dir)

    if not cfg.mirrors:
        rprint("[yellow]No mirrors configured.[/yellow]")
        return

    targets = _resolve_sync_targets(cfg, names, skip_disabled=False)

    table = Table(title="Mirror Status", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("Enabled")
    table.add_column("Last Status")
    table.add_column("Last Sync")
    table.add_column("Last Size")
    table.add_column("Trend")

    for mirror in targets:
        style = _status_style(mirror.last_status)
        size_str = format_size(mirror.last_size) if mirror.last_size else "—"
        trend = "—"
        if mirror.last_size is not None and mirror.previous_size is not None:
            delta = mirror.last_size - mirror.previous_size
            if delta > 0:
                trend = f"[green]+{format_size(delta)}[/green]"
            elif delta < 0:
                trend = f"[red]-{format_size(abs(delta))}[/red]"
            else:
                trend = "[dim]0 B[/dim]"
        table.add_row(
            mirror.name,
            "[green]✓[/green]" if mirror.enabled else "[red]✗[/red]",
            f"[{style}]{mirror.last_status.value}[/{style}]",
            mirror.last_sync.strftime("%Y-%m-%d %H:%M UTC")
            if mirror.last_sync
            else "—",
            size_str,
            trend,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# xync log
# ---------------------------------------------------------------------------


@app.command()
def log(
    name: Annotated[str, typer.Argument(help="Mirror name.")],
    lines: Annotated[
        int, typer.Option("--lines", "-n", help="Number of lines to show.")
    ] = 50,
    config_dir: ConfigDirOption = None,
) -> None:
    """Show the latest sync log for a mirror."""
    cfg = load_config(config_dir)
    _get_mirror(cfg, name)  # ensure it exists

    cfg_dir = get_config_dir(config_dir)
    log_dir_base = (
        Path(cfg.global_config.log_dir)
        if cfg.global_config.log_dir
        else cfg_dir / "logs"
    )
    log_dir = log_dir_base / name

    logs = sorted(log_dir.glob(f"{name}-*.log"))
    if not logs:
        rprint(f"[yellow]No log files found for mirror[/yellow] [bold]{name}[/bold].")
        return

    latest = logs[-1]
    rprint(f"[dim]Log file:[/dim] {latest}\n")

    with latest.open(encoding="utf-8") as fh:
        all_lines = fh.readlines()

    output_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
    for line in output_lines:
        rprint(line, end="")


# ---------------------------------------------------------------------------
# xync health
# ---------------------------------------------------------------------------


@app.command()
def health(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(help="Mirror name(s). Omit to check all mirrors."),
    ] = None,
    config_dir: ConfigDirOption = None,
) -> None:
    """Check local xync configuration, tools, paths, and disk usage."""
    cfg = load_config(config_dir)
    cfg_path = get_config_path(config_dir)
    cfg_dir = get_config_dir(config_dir)

    table = Table(title="xync Health", show_lines=True)
    table.add_column("Check", style="bold cyan")
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("Details")

    errors = 0
    warnings = 0

    def add_row(check: str, target: str, state: str, details: str) -> None:
        nonlocal errors, warnings
        if state == "error":
            errors += 1
            status = "[red]error[/red]"
        elif state == "warning":
            warnings += 1
            status = "[yellow]warning[/yellow]"
        else:
            status = "[green]ok[/green]"
        table.add_row(check, target, status, details)

    add_row(
        "config",
        str(cfg_path),
        "ok" if cfg_path.exists() else "warning",
        "file exists" if cfg_path.exists() else "using default configuration",
    )
    add_row("config dir", str(cfg_dir), "ok", "directory is available")

    required_tools = _required_tools(cfg)
    if not required_tools:
        add_row("tools", "-", "warning", "no mirrors configured")
    for tool in sorted(required_tools):
        add_row(
            "tool",
            tool,
            "ok" if shutil.which(tool) else "error",
            "found on PATH" if shutil.which(tool) else "not found on PATH",
        )

    tg = cfg.global_config.telegram
    if tg.bot_token and not tg.chat_id:
        add_row("telegram", "config", "warning", "bot_token set but chat_id missing")
    elif tg.chat_id and not tg.bot_token:
        add_row("telegram", "config", "warning", "chat_id set but bot_token missing")

    dc = cfg.global_config.discord
    if dc.webhook_url:
        if not dc.webhook_url.startswith("https://"):
            add_row("discord", "config", "error", "webhook_url must use HTTPS")
        elif not dc.webhook_url.startswith("https://discord.com/api/webhooks/"):
            add_row(
                "discord",
                "config",
                "warning",
                "webhook_url does not look like a Discord webhook URL",
            )

    targets = (
        _resolve_sync_targets(cfg, names, skip_disabled=False)
        if cfg.mirrors or names
        else []
    )

    for mirror in targets:
        expected_scheme = _expected_scheme_status(mirror)
        add_row(
            "url",
            mirror.name,
            "ok" if expected_scheme is None else "error",
            expected_scheme or mirror.url,
        )

        parent = Path(mirror.local_path).parent
        if not parent.exists():
            add_row("path", mirror.name, "error", f"parent missing: {parent}")
            continue
        if not os.access(parent, os.W_OK):
            add_row("path", mirror.name, "error", f"parent not writable: {parent}")
        else:
            add_row("path", mirror.name, "ok", f"parent writable: {parent}")

        usage = disk_usage_for_path(mirror.local_path)
        if usage is None:
            add_row("disk", mirror.name, "error", "cannot read filesystem usage")
            continue
        usage_percent, usage_path = usage
        threshold = cfg.global_config.disk_usage_warning_percent
        state = "warning" if usage_percent >= threshold else "ok"
        add_row(
            "disk",
            mirror.name,
            state,
            f"{usage_percent:.1f}% used at {usage_path} (threshold {threshold}%)",
        )

    console.print(table)
    if errors:
        rprint(f"[red]{errors} error(s), {warnings} warning(s).[/red]")
        raise typer.Exit(1)
    if warnings:
        rprint(f"[yellow]{warnings} warning(s).[/yellow]")
    else:
        rprint("[green]✓ Health check passed.[/green]")


# ---------------------------------------------------------------------------
# xync config show
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    config_dir: ConfigDirOption = None,
) -> None:
    """Show the current global configuration."""
    cfg = load_config(config_dir)
    cfg_path = get_config_path(config_dir)

    rprint(f"[dim]Config file:[/dim] {cfg_path}\n")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    gc = cfg.global_config
    table.add_row("default_rsync_options", " ".join(gc.default_rsync_options))
    table.add_row("log_dir", gc.log_dir or "(config_dir/logs)")
    table.add_row("max_log_files", str(gc.max_log_files))
    table.add_row("parallel_jobs", str(gc.parallel_jobs))
    table.add_row("daemon_interval", str(gc.daemon_interval))
    table.add_row("daemon_schedule", gc.daemon_schedule or "(not set)")
    table.add_row("api_enabled", str(gc.api_enabled))
    table.add_row("api_port", str(gc.api_port))
    table.add_row(
        "disk_usage_warning_percent",
        str(gc.disk_usage_warning_percent),
    )
    table.add_row("mirrors_count", str(len(cfg.mirrors)))
    tg = gc.telegram
    masked_token = (tg.bot_token[:6] + "…") if tg.bot_token else "(not set)"
    table.add_row("telegram.bot_token", masked_token)
    table.add_row("telegram.chat_id", tg.chat_id or "(not set)")
    table.add_row("telegram.notify_on_success", str(tg.notify_on_success))
    table.add_row("telegram.notify_on_failure", str(tg.notify_on_failure))
    table.add_row("telegram.notify_on_start", str(tg.notify_on_start))
    table.add_row("telegram.notify_on_finish", str(tg.notify_on_finish))
    table.add_row("telegram.notify_on_progress", str(tg.notify_on_progress))
    dc = gc.discord
    masked_webhook = "(not set)"
    if dc.webhook_url:
        prefix = "https://discord.com/api/webhooks/"
        if dc.webhook_url.startswith(prefix):
            masked_webhook = prefix + "…" + dc.webhook_url[-6:]
        else:
            chunk = dc.webhook_url[:12] + "…"
            masked_webhook = chunk if len(dc.webhook_url) > 12 else dc.webhook_url
    table.add_row("discord.webhook_url", masked_webhook)
    table.add_row("discord.notify_on_success", str(dc.notify_on_success))
    table.add_row("discord.notify_on_failure", str(dc.notify_on_failure))
    table.add_row("discord.notify_on_start", str(dc.notify_on_start))
    table.add_row("discord.notify_on_finish", str(dc.notify_on_finish))
    table.add_row("discord.notify_on_progress", str(dc.notify_on_progress))

    console.print(table)


# ---------------------------------------------------------------------------
# xync config set
# ---------------------------------------------------------------------------


@config_app.command("set")
def config_set(
    key: Annotated[
        str,
        typer.Argument(help="Config key (e.g. max_log_files, parallel_jobs, log_dir)."),
    ],
    value: Annotated[str, typer.Argument(help="New value.")],
    config_dir: ConfigDirOption = None,
) -> None:
    """Set a global configuration value."""
    cfg = load_config(config_dir)
    gc = cfg.global_config

    _set_global_config_value(gc, key, value)

    cfg.global_config = gc
    save_config(cfg, config_dir)
    rprint(f"[green]✓[/green] Set [bold]{key}[/bold] = {value!r}")


def _set_global_config_value(gc: GlobalConfig, key: str, value: str) -> None:
    if "." in key:
        section, _, attr = key.partition(".")
        target = getattr(gc, section, None)
        if target is None or attr not in type(target).model_fields:
            _unknown_config_key(key)
        _set_config_field(target, attr, value)
        return

    if key not in GlobalConfig.model_fields:
        _unknown_config_key(key)
    _set_config_field(gc, key, value)


def _set_config_field(obj, attr: str, value: str) -> None:
    """Set a config field from a string, coercing by the field's declared type."""
    annotation = type(obj).model_fields[attr].annotation
    if annotation is int:
        parsed = _parse_config_int(attr, value)
        if attr == "disk_usage_warning_percent" and not 1 <= parsed <= 100:
            rprint(
                "[red]Error:[/red] 'disk_usage_warning_percent' must be "
                "between 1 and 100."
            )
            raise typer.Exit(1)
        setattr(obj, attr, parsed)
    elif annotation is bool:
        setattr(obj, attr, _parse_config_bool(attr, value))
    elif get_origin(annotation) is list:
        setattr(obj, attr, value.split())
    elif annotation is str:
        setattr(obj, attr, value)
    elif get_origin(annotation) is Union and type(None) in get_args(annotation):
        setattr(obj, attr, value or None)
    else:
        # Nested model (telegram/discord) or unsupported type: not directly settable.
        _unknown_config_key(attr)


def _unknown_config_key(key: str) -> None:
    valid = ", ".join(_valid_config_keys())
    rprint(f"[red]Error:[/red] Unknown key '{key}'. Valid keys: {valid}")
    raise typer.Exit(1)


def _parse_config_int(key: str, value: str) -> int:
    try:
        return int(value)
    except ValueError:
        rprint(f"[red]Error:[/red] '{key}' requires an integer value.")
        raise typer.Exit(1)


def _parse_config_bool(key: str, value: str) -> bool:
    lowered = value.lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    rprint(f"[red]Error:[/red] '{key}' requires a boolean value (true/false).")
    raise typer.Exit(1)


def _valid_config_keys() -> list[str]:
    nested = ("telegram", "discord")
    keys = set(GlobalConfig.model_fields) - set(nested)
    for section in nested:
        sub_model = GlobalConfig.model_fields[section].annotation
        keys |= {f"{section}.{name}" for name in sub_model.model_fields}
    return sorted(keys)


# ---------------------------------------------------------------------------
# xync daemon start / stop / status
# ---------------------------------------------------------------------------


@daemon_app.command("start")
def daemon_start(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Mirror name(s) to sync. Omit to sync all enabled mirrors."
        ),
    ] = None,
    interval: Annotated[
        Optional[int],
        typer.Option(
            "--interval",
            "-i",
            help="Sync interval in seconds. Overrides daemon_interval from config.",
            show_default=False,
        ),
    ] = None,
    api: Annotated[
        bool,
        typer.Option(
            "--api",
            "-a",
            help="Enable API server alongside daemon.",
        ),
    ] = False,
    api_port: Annotated[
        Optional[int],
        typer.Option(
            "--api-port",
            help="API server port. Overrides api_port from config.",
        ),
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option(
            "--foreground",
            "-f",
            help="Run in foreground (for systemd).",
        ),
    ] = False,
    config_dir: ConfigDirOption = None,
) -> None:
    """Start the background sync daemon.

    The daemon forks into the background and keeps running even after the
    terminal is closed or the user logs out.  Sync results are written to
    the daemon log file inside the config directory.
    """
    from xync.daemon import (  # noqa: PLC0415
        daemonize,
        get_daemon_log_file,
        get_pid_file,
        is_running,
        read_pid,
        run_daemon_loop,
    )

    cfg = load_config(config_dir)
    cfg_dir = get_config_dir(config_dir)
    pid_file = get_pid_file(cfg_dir)

    if is_running(pid_file):
        existing_pid = read_pid(pid_file)
        rprint(f"[yellow]Daemon is already running (PID {existing_pid}).[/yellow]")
        raise typer.Exit(1)

    sync_interval = (
        interval if interval is not None else cfg.global_config.daemon_interval
    )
    log_file = get_daemon_log_file(cfg_dir)

    enable_api = api or cfg.global_config.api_enabled
    final_api_port = api_port if api_port is not None else cfg.global_config.api_port

    if enable_api:
        rprint(
            f"[green]Starting xync daemon[/green] "
            f"(interval={sync_interval}s, log={log_file}, "
            f"api=enabled, port={final_api_port})"
        )
    else:
        rprint(
            f"[green]Starting xync daemon[/green] "
            f"(interval={sync_interval}s, log={log_file})"
        )

    if not foreground:
        daemonize(log_file)
    run_daemon_loop(
        cfg_dir, names if names else None, sync_interval, enable_api, final_api_port
    )


@daemon_app.command("stop")
def daemon_stop(
    config_dir: ConfigDirOption = None,
    force: bool = typer.Option(
        False, "--force", help="Send SIGKILL instead of SIGTERM."
    ),
) -> None:
    """Stop the running background sync daemon."""
    from xync.daemon import (
        get_pid_file,
        is_running,
        read_pid,
        stop_daemon,
    )

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_pid_file(cfg_dir)

    if not is_running(pid_file):
        rprint("[yellow]Daemon is not running.[/yellow]")
        return

    pid = read_pid(pid_file)
    if stop_daemon(pid_file, force):
        sig = "SIGKILL" if force else "SIGTERM"
        rprint(f"[green]✓ Sent {sig} to daemon (PID {pid}).[/green]")
    else:
        rprint("[red]Failed to stop daemon.[/red]")
        raise typer.Exit(1)


@daemon_app.command("status")
def daemon_status(
    config_dir: ConfigDirOption = None,
) -> None:
    """Show whether the background sync daemon is running."""
    from xync.daemon import (
        get_daemon_log_file,
        get_pid_file,
        is_running,
        read_pid,
    )

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_pid_file(cfg_dir)
    log_file = get_daemon_log_file(cfg_dir)

    if is_running(pid_file):
        pid = read_pid(pid_file)
        rprint(f"[green]● Daemon is running[/green] (PID {pid})")
        rprint(f"  [dim]log →[/dim] {log_file}")
    else:
        rprint("[dim]○ Daemon is not running[/dim]")


@daemon_app.command("restart")
def daemon_restart(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Mirror name(s) to sync. Omit to sync all enabled mirrors."
        ),
    ] = None,
    interval: Annotated[
        Optional[int],
        typer.Option(
            "--interval",
            "-i",
            help="Sync interval in seconds. Overrides daemon_interval from config.",
            show_default=False,
        ),
    ] = None,
    api: Annotated[
        bool,
        typer.Option(
            "--api",
            "-a",
            help="Enable API server alongside daemon.",
        ),
    ] = False,
    api_port: Annotated[
        Optional[int],
        typer.Option(
            "--api-port",
            help="API server port. Overrides api_port from config.",
        ),
    ] = None,
    config_dir: ConfigDirOption = None,
    force: bool = typer.Option(
        False, "--force", help="Use SIGKILL to stop the daemon."
    ),
) -> None:
    """Restart the background sync daemon."""
    from xync.daemon import (
        get_pid_file,
        is_running,
        read_pid,
        stop_daemon,
    )

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_pid_file(cfg_dir)

    if is_running(pid_file):
        pid = read_pid(pid_file)
        if stop_daemon(pid_file, force):
            sig = "SIGKILL" if force else "SIGTERM"
            rprint(f"[yellow]Stopping daemon ({sig}, PID {pid})...[/yellow]")
            time.sleep(1)
        else:
            rprint("[red]Failed to stop daemon.[/red]")
            raise typer.Exit(1)

    daemon_start(
        names=names,
        interval=interval,
        api=api,
        api_port=api_port,
        config_dir=config_dir,
    )


_SYSTEMD_UNIT = """\
[Unit]
Description=xync mirror sync daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5

[Install]
WantedBy={wanted_by}
"""


@daemon_app.command("install")
def daemon_install(
    names: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Mirror name(s) to sync. Omit to sync all enabled mirrors."
        ),
    ] = None,
    system: Annotated[
        bool,
        typer.Option("--system", help="Install as system service (requires root)."),
    ] = False,
    config_dir: ConfigDirOption = None,
) -> None:
    """Install xync daemon as a systemd service."""
    import subprocess  # noqa: PLC0415

    cfg_dir = get_config_dir(config_dir)
    xync_bin = shutil.which("xync")
    if not xync_bin:
        rprint("[red]Error:[/red] xync not found on PATH.")
        raise typer.Exit(1)

    cmd_parts = [xync_bin, "daemon", "start", "--foreground", "-C", str(cfg_dir)]
    if names:
        cmd_parts.extend(names)
    exec_start = " ".join(cmd_parts)

    if system:
        unit_dir = Path("/etc/systemd/system")
        wanted_by = "multi-user.target"
        systemctl = ["systemctl"]
    else:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        wanted_by = "default.target"
        systemctl = ["systemctl", "--user"]

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "xync-daemon.service"
    unit_path.write_text(
        _SYSTEMD_UNIT.format(exec_start=exec_start, wanted_by=wanted_by)
    )

    subprocess.run([*systemctl, "daemon-reload"], check=True)
    subprocess.run([*systemctl, "enable", "--now", "xync-daemon"], check=True)
    rprint(f"[green]✓ Installed and started xync-daemon service[/green] ({unit_path})")


@daemon_app.command("uninstall")
def daemon_uninstall(
    system: Annotated[
        bool,
        typer.Option("--system", help="Remove system service (requires root)."),
    ] = False,
) -> None:
    """Remove the xync daemon systemd service."""
    import subprocess  # noqa: PLC0415

    if system:
        unit_path = Path("/etc/systemd/system/xync-daemon.service")
        systemctl = ["systemctl"]
    else:
        unit_path = Path.home() / ".config" / "systemd" / "user" / "xync-daemon.service"
        systemctl = ["systemctl", "--user"]

    if not unit_path.exists():
        rprint("[yellow]Service unit file not found.[/yellow]")
        return

    subprocess.run([*systemctl, "disable", "--now", "xync-daemon"], check=False)
    unit_path.unlink()
    subprocess.run([*systemctl, "daemon-reload"], check=True)
    rprint("[green]✓ Removed xync-daemon service.[/green]")


# ---------------------------------------------------------------------------
# xync notify test
# ---------------------------------------------------------------------------


@notify_app.command("test")
def notify_test(
    channel: Annotated[
        str,
        typer.Argument(help="Notification channel: telegram, discord, or all."),
    ] = "all",
    config_dir: ConfigDirOption = None,
) -> None:
    """Send a test notification through one or all configured channels."""
    cfg = load_config(config_dir)
    channel = channel.lower()
    if channel not in {"telegram", "discord", "all"}:
        rprint("[red]Error:[/red] channel must be telegram, discord, or all.")
        raise typer.Exit(1)

    results: list[tuple[str, bool]] = []
    channels = ["telegram", "discord"] if channel == "all" else [channel]
    for ch in channels:
        results.append((ch, send_test_notification(cfg.global_config, ch)))

    failed = False
    for name, ok in results:
        if ok:
            rprint(f"[green]✓[/green] Sent {name} test notification.")
        else:
            failed = True
            rprint(
                f"[red]✗[/red] Could not send {name} test notification. "
                "Check configuration and network access."
            )

    if failed:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_mirror(cfg: xyncConfig, name: str) -> Mirror:
    if name not in cfg.mirrors:
        rprint(f"[red]Error:[/red] Mirror [bold]{name}[/bold] not found.")
        raise typer.Exit(1)
    return cfg.mirrors[name]


def _resolve_sync_targets(
    cfg: xyncConfig,
    names: Optional[list[str]],
    skip_disabled: bool = True,
) -> list[Mirror]:
    """Return the list of mirrors to operate on."""
    if names:
        mirrors = []
        for n in names:
            mirrors.append(_get_mirror(cfg, n))
        return mirrors

    mirrors = list(cfg.mirrors.values())
    if skip_disabled:
        mirrors = [m for m in mirrors if m.enabled]
    return mirrors


def _required_tools(cfg: xyncConfig) -> set[str]:
    tools: set[str] = set()
    for mirror in cfg.mirrors.values():
        if mirror.mirror_type == MirrorType.RSYNC:
            tools.add("rsync")
        elif mirror.mirror_type in (MirrorType.HTTP, MirrorType.FTP):
            tools.add("wget")
    return tools


def _expected_scheme_status(mirror: Mirror) -> Optional[str]:
    if mirror.mirror_type == MirrorType.RSYNC and not mirror.url.startswith("rsync://"):
        return "rsync mirrors should use rsync:// URLs"
    if mirror.mirror_type == MirrorType.HTTP and not mirror.url.startswith(
        ("http://", "https://")
    ):
        return "http mirrors should use http:// or https:// URLs"
    if mirror.mirror_type == MirrorType.FTP and not mirror.url.startswith("ftp://"):
        return "ftp mirrors should use ftp:// URLs"
    return None


def _status_style(status: SyncStatus) -> str:
    return {
        SyncStatus.SUCCESS: "green",
        SyncStatus.FAILED: "red",
        SyncStatus.RUNNING: "yellow",
        SyncStatus.PENDING: "blue",
        SyncStatus.NEVER: "dim",
    }.get(status, "white")


# ---------------------------------------------------------------------------
# xync api start / stop / status
# ---------------------------------------------------------------------------


@api_app.command("start")
def api_start(
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="API server port."),
    ] = 58080,
    config_dir: ConfigDirOption = None,
) -> None:
    """Start the API server."""
    from xync.api import get_api_pid_file, init_api_state, run_api_server
    from xync.daemon import is_running

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_api_pid_file(cfg_dir)

    if is_running(pid_file):
        rprint("[yellow]API server is already running.[/yellow]")
        raise typer.Exit(1)

    init_api_state(config_dir)
    rprint(f"[green]Starting xync API server[/green] on port {port}")
    rprint(f"[dim]Config directory: {cfg_dir}[/dim]")
    rprint(f"[dim]API endpoint: http://0.0.0.0:{port}/api/status[/dim]")
    try:
        run_api_server(port=port, pid_file=pid_file)
    except KeyboardInterrupt:
        rprint()


@api_app.command("stop")
def api_stop(
    config_dir: ConfigDirOption = None,
    force: bool = typer.Option(
        False, "--force", help="Send SIGKILL instead of SIGTERM."
    ),
) -> None:
    """Stop a running API server process."""
    from xync.api import get_api_pid_file
    from xync.daemon import is_running, read_pid, stop_daemon

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_api_pid_file(cfg_dir)

    if not is_running(pid_file):
        rprint("[yellow]API server is not running.[/yellow]")
        return

    pid = read_pid(pid_file)
    if stop_daemon(pid_file, force):
        sig = "SIGKILL" if force else "SIGTERM"
        rprint(f"[green]Sent {sig} to API server (PID {pid}).[/green]")
    else:
        rprint("[red]Failed to stop API server.[/red]")
        raise typer.Exit(1)


@api_app.command("status")
def api_status(
    config_dir: ConfigDirOption = None,
) -> None:
    """Show whether the API server is running."""
    from xync.api import get_api_pid_file
    from xync.daemon import is_running, read_pid

    cfg_dir = get_config_dir(config_dir)
    pid_file = get_api_pid_file(cfg_dir)

    if is_running(pid_file):
        pid = read_pid(pid_file)
        cfg = load_config(config_dir)
        port = cfg.global_config.api_port
        rprint(f"[green]API server is running[/green] (PID {pid}, port {port})")
        rprint(f"  [dim]endpoint →[/dim] http://0.0.0.0:{port}/api/status")
    else:
        rprint("[dim]API server is not running[/dim]")


if __name__ == "__main__":
    app()
