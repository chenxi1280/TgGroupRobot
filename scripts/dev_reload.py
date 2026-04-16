from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_WATCH_PATHS = (
    "main.py",
    "backend",
    "config",
    ".env",
    "env",
    "requirements.txt",
)

WATCH_SUFFIXES = {".py", ".env", ".ini", ".toml", ".yaml", ".yml"}
WATCH_FILE_NAMES = {".env", "env", "requirements.txt"}
IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "htmlcov",
}


Snapshot = dict[Path, tuple[int, int]]


def _normalize_watch_paths(paths: Sequence[str] | None) -> list[Path]:
    selected = list(paths or DEFAULT_WATCH_PATHS)
    return [(PROJECT_ROOT / path).resolve() for path in selected]


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def _should_watch_file(path: Path) -> bool:
    if _is_ignored(path):
        return False
    return path.name in WATCH_FILE_NAMES or path.suffix in WATCH_SUFFIXES


def _iter_watch_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            if _should_watch_file(path):
                yield path
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if child.is_file() and _should_watch_file(child):
                yield child


def build_snapshot(paths: Sequence[str] | None = None) -> Snapshot:
    snapshot: Snapshot = {}
    for path in _iter_watch_files(_normalize_watch_paths(paths)):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path.relative_to(PROJECT_ROOT)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def changed_paths(before: Snapshot, after: Snapshot) -> list[Path]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def wait_for_change(
    snapshot: Snapshot,
    *,
    watch_paths: Sequence[str] | None,
    poll_interval: float,
    debounce_seconds: float,
) -> tuple[Snapshot, list[Path]]:
    while True:
        time.sleep(poll_interval)
        next_snapshot = build_snapshot(watch_paths)
        changed = changed_paths(snapshot, next_snapshot)
        if not changed:
            continue

        if debounce_seconds > 0:
            time.sleep(debounce_seconds)
            next_snapshot = build_snapshot(watch_paths)
            changed = changed_paths(snapshot, next_snapshot)
            if not changed:
                continue

        return next_snapshot, changed


def _format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def start_process(command: Sequence[str]) -> subprocess.Popen[bytes]:
    print(f"[reload] starting: {_format_command(command)}", flush=True)
    return subprocess.Popen(command, cwd=PROJECT_ROOT)


def stop_process(process: subprocess.Popen[bytes], *, grace_period: float) -> None:
    if process.poll() is not None:
        return

    print("[reload] stopping current bot...", flush=True)
    if os.name == "nt":
        process.terminate()
    else:
        process.send_signal(signal.SIGTERM)

    try:
        process.wait(timeout=grace_period)
    except subprocess.TimeoutExpired:
        print("[reload] graceful stop timed out; killing process.", flush=True)
        process.kill()
        process.wait(timeout=5)


def _parse_command(raw_command: Sequence[str]) -> list[str]:
    if raw_command and raw_command[0] == "--":
        raw_command = raw_command[1:]
    return list(raw_command) or [sys.executable, "main.py"]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Telegram bot with development auto-reload.")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between file change scans. Default: 1.0",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=0.3,
        help="Seconds to wait for editors to finish writing changed files. Default: 0.3",
    )
    parser.add_argument(
        "--grace-period",
        type=float,
        default=10.0,
        help="Seconds to wait for the bot to stop before killing it. Default: 10.0",
    )
    parser.add_argument(
        "--watch",
        action="append",
        default=None,
        help="Extra path to watch. Can be passed more than once.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run after --. Default: current Python executable + main.py",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    watch_paths = list(DEFAULT_WATCH_PATHS)
    if args.watch:
        watch_paths.extend(args.watch)

    command = _parse_command(args.command)
    snapshot = build_snapshot(watch_paths)
    process = start_process(command)

    print("[reload] watching for code changes. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            snapshot, changed = wait_for_change(
                snapshot,
                watch_paths=watch_paths,
                poll_interval=args.poll_interval,
                debounce_seconds=args.debounce,
            )
            changed_text = ", ".join(str(path) for path in changed[:5])
            if len(changed) > 5:
                changed_text += f", ... +{len(changed) - 5} more"
            print(f"[reload] change detected: {changed_text}", flush=True)
            stop_process(process, grace_period=args.grace_period)
            process = start_process(command)
    except KeyboardInterrupt:
        print("\n[reload] stopping.", flush=True)
        stop_process(process, grace_period=args.grace_period)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
