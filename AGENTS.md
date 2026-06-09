# AGENTS.md — xync

Linux mirror sync/management CLI. Python (Typer + Rich + FastAPI), packaged with `uv` and `hatchling`, published to PyPI. Also ships a PyInstaller standalone binary.

## Layout

- `src/xync/` — package source. CLI entry: `src/xync/main.py` (Typer `app`).
  - `main.py` — all `@app.command()` definitions (init, mirror *, sync, status, log, health, config *, daemon *, notify, api *).
  - `config.py` — TOML config load/save, default config dir resolution.
  - `models.py` — Pydantic models; `xyncConfig.version: int = 1` is the config schema version.
  - `sync.py` — `sync_mirror`, `diff_mirror`, `purge_old_logs`, `SyncResult`.
  - `daemon.py` — background scheduler (interval or cron), PID/log files in config dir.
  - `api.py` — FastAPI/uvicorn server (`/api/status`, `/api/mirrors`, `/api/mirrors/{name}`, `/api/mirrors/{name}/size`).
  - `telegram.py`, `discord.py` — notifiers.
  - `utils.py` — disk usage, progress callbacks.
- `tests/` — pytest suite. `__init__.py` present. Test files: `test_cli.py`, `test_config.py`, `test_models.py`, `test_sync.py`, `test_discord.py`, `test_telegram.py`.
- `xync.spec` — PyInstaller spec for standalone binary (`./dist/xync`).
- `scripts/test-executable.sh` — smoke-tests the PyInstaller binary (version, help, init, config show, mirror list in a temp dir).
- `.github/workflows/pypi.yml` — CI: test + build on PR/push to `main`; publish to PyPI on GitHub release.

## Setup & common commands

```bash
uv sync                 # install deps (dev + runtime)
uv run xync --help      # run CLI from source
uv run pytest           # run full test suite
uv run pytest tests/test_cli.py -v          # one test file
uv run pytest tests/test_cli.py::TestFoo -v # one test
uv run ruff check src/ tests/   # lint (E, F, I)
uv build                # build sdist + wheel into dist/
```

Pre-commit / formatter: **none configured** — only `ruff check` (no `format`, no `isort` config beyond the I rules). Don't add unrelated tooling without being asked.

PyInstaller binary (optional):
```bash
pip install pyinstaller
pyinstaller xync.spec
./dist/xync --version
./scripts/test-executable.sh
```

## Python version

- `pyproject.toml` requires `>=3.11`.
- `.python-version` pins **3.14**. Mismatch with lockfile is intentional — CI/dev uses 3.14; package metadata still advertises 3.11+.

## Configuration (runtime, not dev)

- Default config dir: `~/.config/xync/`. Override with `--config-dir`/`-C` or env var **`xync_CONFIG_DIR`** (note: lowercase `xync_` prefix, not `XYNC_`).
- Config file: `config.toml` (TOML). Schema versioned via top-level `version = 1` (alongside `[global]`); `xyncConfig.version`. Bump only with a migration path in config loading.
- Mirror names: `[A-Za-z0-9_-]+` only — validated on add.

## Runtime requirements (documented in README, easy to forget)

The CLI shells out to `rsync` and `wget`; they must be on `PATH` for `sync`/`diff` to work, and `xync health` will flag them as missing.

## CI / publishing

- Workflow runs on a **self-hosted runner** (`runs-on: self-hosted`), not GitHub-hosted. Don't change to `ubuntu-latest` without confirming a runner exists.
- Publish step is gated on `release` event with action `published` and uses trusted publishing (`id-token: write`). Manual `workflow_dispatch` is also enabled.
- After build, runs `uvx twine check --strict dist/*`.

## Things easy to miss

- **PyInstaller hidden imports**: `xync.spec` explicitly lists uvicorn submodules (`uvicorn.logging`, `uvicorn.loops.auto`, `uvicorn.protocols.*`, `uvicorn.lifespan.on`). If you add an uvicorn plugin/extension, add it here or the binary will fail at runtime. (Also note `strip=True, upx=True` on the EXE.)
- **Mirror name validation** lives in `models.py` and is enforced both at CLI and in config loading — re-use the validator, don't roll a new regex.
- **`mirror diff` is rsync-only** (uses `rsync --dry-run --itemize-changes`). HTTP/FTP mirrors will error — preserve this restriction.
- **Notifications** import re-exports in `main.py` (e.g. `notify_sync_result as notify_telegram` from `xync.telegram`). Keep that pattern when adding new notifier events; the rename avoids clashes between telegram/discord.
- **Daemon PID + log files** live inside the config dir — if a test sets a custom `--config-dir` it must use `tmp_path` or `mkdtemp`, not the user's real config.
- The CLI default config dir is per-user; tests that mutate config must isolate `--config-dir`.
- The PyInstaller `EXE` strips symbols and runs UPX — debug builds need `strip=False, upx=False`.
